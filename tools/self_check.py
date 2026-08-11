from pathlib import Path
import datetime
import cv2
import numpy as np
from queue import Queue
import signal
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from camera import Camera, is_bad_frame
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
)


def main():
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

    bad_sample = ROOT / "img_log/kt-sdp/20260811/debug/detected_camwb02_right_2026-08-11_16-50-52_raw.png"
    normal_sample = ROOT / "img_log/kt-sdp/20260811/debug/detected_camwb02_right_2026-08-11_17-16-57_raw.png"
    if bad_sample.exists() and normal_sample.exists():
        assert is_bad_frame(cv2.imread(str(bad_sample)))
        assert not is_bad_frame(cv2.imread(str(normal_sample)))

    assert Camera.__init__.__defaults__[3] is True

    camera = Camera.__new__(Camera)
    camera.rtsp = "rtsp://example"
    camera.reject_bad_frames = True
    camera.ret = False
    camera.frame = None
    camera.bad_frame_count = 0
    camera._accept_frame(True, bad_gray)
    assert camera.ret is False
    assert camera.frame is None
    assert camera.bad_frame_count == 1

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
