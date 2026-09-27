from pathlib import Path
import datetime
import cv2
import numpy as np
from queue import Queue
import signal
import sys
import tempfile
import subprocess
import threading
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from camera import Camera, is_bad_frame
from tools import calibrate_zone
from shapely.geometry import Polygon

from main import (
    bbox_matches_danger_zone,
    clamp_zone_crop_box,
    cleanup_processes,
    cleanup_date_dirs,
    deduplicate_overlapping_detections,
    deduplicate_overlapping_detections_with_metadata,
    draw_debug_overlay,
    install_shutdown_handlers,
    openvino_model_ready,
    passes_class_and_filter,
    polygon_debug_points,
    put_latest_display_frame,
    read_danger_zones,
    zone_crop_boxes,
    camera_process_worker,
)


def check_camera_health():
    with patch.object(Camera, "_open_ffmpeg"):
        camera = Camera("rtsp://example", width=2, height=2, reject_bad_frames=False)
    camera.process = Mock()
    camera.process.poll.return_value = None
    started_at = camera.last_frame_time
    with patch("camera.time.monotonic", return_value=started_at + 10):
        assert camera.get_data() is None and camera.is_opened()
        assert camera.frame_wait_remaining() == 50
    with patch("camera.time.monotonic", return_value=started_at + 59.999):
        assert camera.is_opened()
    with patch("camera.time.monotonic", return_value=started_at + 60):
        assert camera.get_data() is None and not camera.is_opened()
    frame = np.arange(12, dtype=np.uint8).reshape(2, 2, 3)
    camera._accept_frame(True, frame)
    received_at = camera.last_frame_time
    with patch("camera.time.monotonic", return_value=received_at + 9.999):
        assert np.array_equal(camera.get_data(), frame)
        assert camera.is_opened()
    with patch("camera.time.monotonic", return_value=received_at + 10):
        assert camera.get_data() is None
        assert not camera.is_opened()
        camera._accept_frame(True, frame)
        assert np.array_equal(camera.get_data(), frame)
        assert camera.frame_seq == 2
    camera.process.poll.return_value = 1
    assert camera.get_data() is None
    camera._update_ffmpeg()
    assert camera.frame is None and not camera.ret
    camera.process.poll.return_value = None
    camera.process.stdout.read.return_value = b'partial'
    camera._accept_frame(True, frame)
    camera._update_ffmpeg()
    assert camera.frame is None and not camera.ret
    camera._accept_frame(True, frame)
    camera.process.stdout.read.side_effect = OSError("reader failed")
    try:
        camera._update_ffmpeg()
    except OSError:
        pass
    else:
        raise AssertionError("reader error swallowed")
    assert camera.frame is None and not camera.ret
    camera._accept_frame(True, frame)
    camera.thread = Mock()
    camera.thread.is_alive.return_value = False
    assert camera.get_data() is None

    for timeout in (0, -1, float("nan"), float("inf")):
        for option in ("frame_timeout", "startup_timeout"):
            try:
                Camera("rtsp://example", **{option: timeout})
            except ValueError:
                pass
            else:
                raise AssertionError("invalid timeout accepted")

    # No version-sensitive FFmpeg timeout flags; probing uses a separate budget.
    process = Mock()
    with patch.object(Camera, "_probe_stream_size", return_value=(2, 2)), patch("camera.subprocess.Popen", return_value=process) as launch, patch("camera.threading.Thread"), patch("camera.time.monotonic", side_effect=[0, 8]):
        opened_camera = Camera("rtsp://example", width=0, height=0)
    assert opened_camera.last_frame_time == 8
    command = launch.call_args.args[0]
    assert '-timeout' not in command and '-stimeout' not in command
    assert launch.call_args.kwargs['stderr'] == subprocess.DEVNULL

    # A real pipe remains blocked after delivering one complete frame.
    with patch.object(Camera, "_open_ffmpeg"):
        camera = Camera("rtsp://example", width=2, height=2, reject_bad_frames=False)
    camera.process = subprocess.Popen(
        [sys.executable, "-c", "import os,time; os.write(2,b'capture error\\n'*10000); os.write(1,bytes(range(12))); time.sleep(30)"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**8,
    )
    accepted = threading.Event()
    original_accept = camera._accept_frame

    def accept(ret, image):
        original_accept(ret, image)
        if ret:
            accepted.set()

    camera._accept_frame = accept
    camera.thread = threading.Thread(target=camera._update_ffmpeg, daemon=True)
    camera.thread.start()
    try:
        assert accepted.wait(5)
        assert np.array_equal(camera.get_data(), frame)
        with patch("camera.time.monotonic", return_value=camera.last_frame_time + 10):
            assert camera.process.poll() is None and camera.thread.is_alive()
            assert camera.get_data() is None and not camera.is_opened()
    finally:
        camera.release()
    assert camera.process.poll() is not None and not camera.thread.is_alive()
    assert camera.process.stdout.closed and camera.frame is None

    # Exercise the worker's reconnect branch without RTSP or model inference.
    old_camera = Mock(frame_seq=1)
    old_camera.get_data.side_effect = [frame, None]
    old_camera.is_opened.return_value = False
    old_camera.frame_age.return_value = 10
    new_camera = Mock()
    stop_event = threading.Event()
    display_queue = Queue(maxsize=2)
    calls = []

    def connect(*args, **kwargs):
        calls.append((args, kwargs))
        if len(calls) == 1:
            return old_camera
        stop_event.set()
        return new_camera

    previous_sigint = signal.getsignal(signal.SIGINT)
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    try:
        with patch("main.Camera", side_effect=connect), patch("main.load_model", return_value=(Mock(), {}, False)), patch("main.warn_unknown_classes"), patch("main.time.sleep"):
            camera_process_worker(
                {"id": "test", "rtsp_url": "rtsp://example"}, None,
                display_queue, stop_event, "", False, 5,
                {"frame_width": 320, "frame_height": 180, "rtsp_frame_timeout_seconds": 12, "rtsp_startup_timeout_seconds": 75}, {}, {}, {},
            )
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)
    assert [args[1] for args, _ in calls] == ["tcp", "udp"]
    assert all(kwargs["frame_timeout"] == 12 for _, kwargs in calls)
    assert all(kwargs["startup_timeout"] == 75 for _, kwargs in calls)
    old_camera.release.assert_called_once()
    new_camera.release.assert_called_once()
    display_queue.get_nowait()  # preview
    _, unavailable = display_queue.get_nowait()
    assert np.count_nonzero(unavailable) > 0
    print("camera health checks ok")


def main():
    check_camera_health()
    class DoneProcess:
        pid = 1

        def join(self, timeout=None):
            signal.raise_signal(signal.SIGINT)

        def is_alive(self):
            return False

    previous_sigint = signal.getsignal(signal.SIGINT)
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    cleanup_processes([DoneProcess()], timeout=0.01)
    assert signal.getsignal(signal.SIGINT) == previous_sigint

    class StubbornProcess:
        pid = 2

        def __init__(self):
            self.terminated = False
            self.killed = False

        def join(self, timeout=None):
            return None

        def is_alive(self):
            return not self.killed

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

    stubborn = StubbornProcess()
    cleanup_processes([stubborn], timeout=0.01)
    assert stubborn.terminated
    assert stubborn.killed

    class StopEvent:
        stopped = False

        def set(self):
            self.stopped = True

    stop_event = StopEvent()
    install_shutdown_handlers(stop_event)
    signal.raise_signal(signal.SIGTERM)
    assert stop_event.stopped
    signal.signal(signal.SIGINT, previous_sigint)
    signal.signal(signal.SIGTERM, previous_sigterm)

    display_queue = Queue(maxsize=1)
    put_latest_display_frame(display_queue, ("cam", "old"))
    put_latest_display_frame(display_queue, ("cam", "new"))
    assert display_queue.get_nowait() == ("cam", "new")

    bad_gray = np.full((180, 320, 3), 132, dtype="uint8")
    bad_gray[40:70, 90:160] = 138
    normal_color = np.zeros((180, 320, 3), dtype="uint8")
    normal_color[:, :160] = (60, 150, 30)
    normal_color[:, 160:] = (210, 80, 40)
    cv2.rectangle(normal_color, (40, 40), (280, 140), (255, 255, 255), 3)
    normal_gray = np.full((180, 320, 3), 120, dtype="uint8")
    for x in range(20, 300, 28):
        cv2.line(normal_gray, (x, 20), (x, 160), (230, 230, 230), 2)
    for y in range(30, 170, 24):
        cv2.line(normal_gray, (20, y), (300, y), (40, 40, 40), 2)
    assert is_bad_frame(bad_gray)
    assert not is_bad_frame(normal_color)
    assert not is_bad_frame(normal_gray)

    class FakeCalibrationCamera:
        def __init__(self, *_args, **_kwargs):
            self.frames = iter((bad_gray, normal_color))

        def get_data(self):
            return next(self.frames, None)

        def release(self):
            pass

    original_camera = calibrate_zone.Camera
    calibrate_zone.Camera = FakeCalibrationCamera
    try:
        calibration_frame = calibrate_zone.grab_frame(
            {"id": "test", "rtsp_url": "fake"},
            {"frame_width": 320, "frame_height": 180},
            1,
        )
        assert np.array_equal(calibration_frame, normal_color)
    finally:
        calibrate_zone.Camera = original_camera

    bad_sample = ROOT / "img_log/kt-sdp/20260811/debug/detected_camwb02_right_2026-08-11_16-50-52_raw.png"
    normal_sample = ROOT / "img_log/kt-sdp/20260811/debug/detected_camwb02_right_2026-08-11_17-16-57_raw.png"
    if bad_sample.exists() and normal_sample.exists():
        assert is_bad_frame(cv2.imread(str(bad_sample)))
        assert not is_bad_frame(cv2.imread(str(normal_sample)))

    assert Camera.__init__.__defaults__[3] is True

    with patch.object(Camera, "_open_ffmpeg"):
        camera = Camera("rtsp://example")
    camera.process = Mock()
    camera.process.poll.return_value = None
    camera._accept_frame(True, bad_gray)
    assert camera.ret is True
    assert camera.frame is bad_gray
    assert camera.get_data() is None
    assert camera.bad_frame_count == 1
    camera._accept_frame(True, normal_color)
    assert camera.get_data().shape == normal_color.shape
    assert camera.bad_frame_count == 0

    zone = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    contact_filter = {"mode": "bottom_line", "line_width_ratio": 0.8, "bottom_offset_ratio": 0.0}
    overlap_filter = {"mode": "overlap", "min_bbox_overlap_ratio": 0.15}
    assert bbox_matches_danger_zone(zone, [10, -40, 50, 10], contact_filter)
    assert not bbox_matches_danger_zone(zone, [10, 110, 50, 150], contact_filter)
    assert bbox_matches_danger_zone(zone, [10, 10, 50, 50], overlap_filter)
    assert not bbox_matches_danger_zone(zone, [90, 90, 190, 190], overlap_filter)
    overlay = draw_debug_overlay(
        __import__("numpy").zeros((120, 120, 3), dtype="uint8"),
        zone,
        {"crop_boxes": [[0, 0, 60, 60]]},
        [[10, 10, 50, 50]],
        ["Person"],
        [0.9],
    )
    assert overlay.shape == (120, 120, 3)
    assert clamp_zone_crop_box(zone, (100, 100, 3), 0.25) == [0, 0, 100, 100]
    assert polygon_debug_points(zone) == [[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0], [0.0, 0.0]]
    flat_zone = Polygon([(40, 80), (140, 80), (140, 90), (40, 90)])
    assert clamp_zone_crop_box(flat_zone, (200, 200, 3), 0.25) == [15, 55, 165, 115]
    wide_zone = Polygon([(0, 0), (1280, 0), (1280, 200), (0, 200)])
    base_crop, tiled_crops = zone_crop_boxes(
        wide_zone,
        (720, 1280, 3),
        {"padding_ratio": 0, "max_crop_width": 640, "max_crop_height": 640, "tile_overlap_ratio": 0.25},
    )
    assert base_crop == [0, 0, 1280, 200]
    assert tiled_crops == [[0, 0, 640, 200], [480, 0, 1120, 200], [640, 0, 1280, 200]]
    _, single_crop = zone_crop_boxes(wide_zone, (720, 1280, 3), {"padding_ratio": 0, "auto_tile": False})
    assert single_crop == [[0, 0, 1280, 200]]
    padded_crop, padded_tiles = zone_crop_boxes(
        Polygon([(0, 300), (1280, 300), (1280, 500), (0, 500)]),
        (720, 1280, 3),
        {"padding_ratio": 0, "top_padding_ratio": 0.5, "max_crop_width": 640, "max_crop_height": 640},
    )
    assert padded_crop == [0, 200, 1280, 500]
    assert padded_tiles == [[0, 200, 640, 500], [480, 200, 1120, 500], [640, 200, 1280, 500]]
    _, bottom_tiles = zone_crop_boxes(
        Polygon([(0, 300), (1280, 300), (1280, 500), (0, 500)]),
        (720, 1280, 3),
        {
            "padding_ratio": 0,
            "top_padding_ratio": 0.5,
            "max_crop_width": 480,
            "max_crop_height": 270,
            "tile_overlap_ratio": 0.25,
            "tile_vertical_anchor": "bottom",
        },
    )
    assert bottom_tiles == [[0, 230, 480, 500], [360, 230, 840, 500], [720, 230, 1200, 500], [800, 230, 1280, 500]]
    multi_base, multi_tiles = zone_crop_boxes(
        Polygon([(0, 300), (1280, 300), (1280, 500), (0, 500)]),
        (720, 1280, 3),
        {
            "multi_scale": True,
            "context_crop": {"enabled": True, "padding_ratio": 0, "top_padding_ratio": 0.5},
            "zoom_crop": {
                "enabled": True,
                "padding_ratio": 0,
                "top_padding_ratio": 0.5,
                "max_crop_width": 480,
                "max_crop_height": 360,
                "tile_overlap_ratio": 0.5,
            },
        },
    )
    assert multi_base == [0, 200, 1280, 500]
    assert multi_tiles == [
        [0, 200, 1280, 500],
        [0, 200, 480, 500],
        [240, 200, 720, 500],
        [480, 200, 960, 500],
        [720, 200, 1200, 500],
        [800, 200, 1280, 500],
    ]

    config_zone = read_danger_zones(
        {"zones": {"regions": {"cam": [[0, 0], [1, 0], [1, 1], [0, 1]]}}},
        [{"id": "cam"}],
        100,
        100,
    )[0]
    assert config_zone.area == 10000
    assert read_danger_zones({"zones": {"regions": {}}}, [{"id": "missing"}], 100, 100, required=False) == [None]

    class_config = {
        "intrusion": ["Person", "Vehicle", "Machinery"],
        "ignore": ["Hardhat"],
    }
    filter_config = {
        "min_confidence_by_class": {"Person": 0.3, "Machinery": 0.3},
        "max_bbox_size": {"enabled": False},
        "edge_confidence": {"enabled": False},
    }
    frame_shape = (720, 1280, 3)
    assert passes_class_and_filter([10, 10, 50, 50], "Person", 0.31, frame_shape, class_config, filter_config)
    assert not passes_class_and_filter([10, 10, 50, 50], "Person", 0.29, frame_shape, class_config, filter_config)
    assert not passes_class_and_filter([10, 10, 50, 50], "Hardhat", 0.99, frame_shape, class_config, filter_config)
    assert passes_class_and_filter([10, 10, 50, 50], "machinery", 0.31, frame_shape, class_config, filter_config)
    assert not passes_class_and_filter([10, 10, 50, 50], "machinery", 0.29, frame_shape, class_config, filter_config)
    assert not passes_class_and_filter([10, 10, 50, 50], "unknown", 0.99, frame_shape, class_config, filter_config)

    dedup_bboxes, dedup_labels, dedup_confidences = deduplicate_overlapping_detections(
        [[10, 10, 60, 60], [12, 12, 58, 58], [12, 12, 58, 58]],
        ["machinery", "Machinery", "Person"],
        [0.8, 0.9, 0.7],
        {"enabled": True, "max_overlap_ratio": 0.8},
    )
    assert dedup_bboxes == [[12, 12, 58, 58], [12, 12, 58, 58]]
    assert dedup_labels == ["Machinery", "Person"]
    assert dedup_confidences == [0.9, 0.7]
    _, _, _, dedup_sources = deduplicate_overlapping_detections_with_metadata(
        [[10, 10, 60, 60], [12, 12, 58, 58], [12, 12, 58, 58]],
        ["machinery", "Machinery", "Person"],
        [0.8, 0.9, 0.7],
        ["full_frame", "zone_crop", "full_frame"],
        {"enabled": True, "max_overlap_ratio": 0.8},
    )
    assert dedup_sources == ["zone_crop", "full_frame"]

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name in ("20260805", "20260730", "20260729", "misc"):
            (root / name).mkdir()
        cleanup_date_dirs(root, days_to_keep=7, today=datetime.date(2026, 8, 5))
        assert (root / "20260805").exists()
        assert (root / "20260730").exists()
        assert not (root / "20260729").exists()
        assert (root / "misc").exists()

    with tempfile.TemporaryDirectory() as tmp:
        model_dir = Path(tmp)
        assert not openvino_model_ready(model_dir)
        (model_dir / "model.xml").write_text("<xml />", encoding="utf-8")
        assert not openvino_model_ready(model_dir)
        (model_dir / "model.bin").write_bytes(b"bin")
        assert not openvino_model_ready(model_dir)

    real_openvino_model = ROOT / "models" / "hf" / "yolo26n_openvino_model"
    if real_openvino_model.exists():
        assert openvino_model_ready(real_openvino_model)

    print("self_check ok")


if __name__ == "__main__":
    main()
