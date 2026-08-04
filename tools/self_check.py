from pathlib import Path
import datetime
import signal
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shapely.geometry import Polygon

from main import (
    bbox_matches_danger_zone,
    cleanup_processes,
    cleanup_date_dirs,
    install_shutdown_handlers,
    openvino_model_ready,
    passes_class_and_filter,
    read_danger_zones,
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

    zone = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    contact_filter = {"mode": "bottom_line", "line_width_ratio": 0.8, "bottom_offset_ratio": 0.0}
    overlap_filter = {"mode": "overlap", "min_bbox_overlap_ratio": 0.15}
    assert bbox_matches_danger_zone(zone, [10, -40, 50, 10], contact_filter)
    assert not bbox_matches_danger_zone(zone, [10, 110, 50, 150], contact_filter)
    assert bbox_matches_danger_zone(zone, [10, 10, 50, 50], overlap_filter)
    assert not bbox_matches_danger_zone(zone, [90, 90, 190, 190], overlap_filter)

    config_zone = read_danger_zones(
        {"zones": {"regions": {"cam": [[0, 0], [1, 0], [1, 1], [0, 1]]}}},
        [{"id": "cam"}],
        100,
        100,
    )[0]
    assert config_zone.area == 10000

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
