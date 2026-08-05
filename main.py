import base64
import datetime
import glob
import json
import logging as log
import logging.handlers
import os
import shutil
import signal
import sys
import threading
import time
from multiprocessing import Event, Process, Queue
from pathlib import Path

import cv2
import numpy as np
import requests
from camera import Camera
from huggingface_hub import hf_hub_download
from shapely.errors import GEOSException
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union
from ultralytics import YOLO
from zoneinfo import ZoneInfo

try:
    from shapely.validation import make_valid
except ImportError:
    make_valid = None

PROJECT_DIR = Path(__file__).resolve().parent
IMG_LOG_DIR = PROJECT_DIR / "img_log"
LOG_DIR = PROJECT_DIR / "log"
RETENTION_DAYS = 7

os.environ["OPENCV_LOG_LEVEL"] = "SILENT"
os.environ["OPENCV_FFMPEG_LOGLEVEL"] = "-8"


def setup_logging():
    LOG_DIR.mkdir(exist_ok=True)
    formatter = log.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    stream_handler = log.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    file_handler = log.handlers.TimedRotatingFileHandler(
        LOG_DIR / "gantry_intrusion.log",
        when="MIDNIGHT",
        interval=1,
        backupCount=RETENTION_DAYS - 1,
        encoding="utf-8",
    )
    file_handler.suffix = "%Y-%m-%d.log"
    file_handler.setFormatter(formatter)
    root_logger = log.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(log.INFO)
    root_logger.addHandler(stream_handler)
    root_logger.addHandler(file_handler)


setup_logging()


def load_config(config_path=None):
    config_path = Path(config_path) if config_path else PROJECT_DIR / "config.json"
    if not config_path.exists():
        log.error("Missing config file: %s", config_path)
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def project_path(path_value):
    if not path_value:
        return None
    path = Path(path_value)
    return path if path.is_absolute() else PROJECT_DIR / path


def cleanup_date_dirs(root_dir, days_to_keep=RETENTION_DAYS, today=None):
    root_dir = Path(root_dir)
    if not root_dir.exists():
        return
    today = today or datetime.date.today()
    cutoff = today - datetime.timedelta(days=max(1, int(days_to_keep)) - 1)
    for path in root_dir.iterdir():
        if not path.is_dir():
            continue
        try:
            folder_date = datetime.datetime.strptime(path.name, "%Y%m%d").date()
        except ValueError:
            continue
        if folder_date < cutoff:
            shutil.rmtree(path)
            log.info("Removed old image log directory: %s", path)


def cleanup_old_log_files(days_to_keep=RETENTION_DAYS, now=None):
    if not LOG_DIR.exists():
        return
    now = now or datetime.datetime.now()
    cutoff = now - datetime.timedelta(days=max(1, int(days_to_keep)))
    for path in LOG_DIR.iterdir():
        if not path.is_file() or path.name == "gantry_intrusion.log":
            continue
        if datetime.datetime.fromtimestamp(path.stat().st_mtime) < cutoff:
            path.unlink()
            log.info("Removed old log file: %s", path)


def cleanup_runtime_outputs():
    cleanup_date_dirs(IMG_LOG_DIR)
    cleanup_old_log_files()


def cleanup_processes(processes, timeout=5):
    previous_sigint = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        log.info("Cleaning up processes...")
        deadline = time.time() + timeout
        for process in processes:
            process.join(timeout=max(0, deadline - time.time()))

        for process in processes:
            if process.is_alive():
                log.warning("Process %s did not terminate gracefully. Terminating.", process.pid)
                process.terminate()

        for process in processes:
            if process.is_alive():
                process.join(timeout=2)

        for process in processes:
            if process.is_alive():
                log.warning("Process %s did not terminate. Killing.", process.pid)
                process.kill()
                process.join(timeout=2)
    finally:
        signal.signal(signal.SIGINT, previous_sigint)


def install_shutdown_handlers(stop_event):
    def request_shutdown(signum, _frame):
        log.info("Shutdown signal %s received. Shutting down.", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)


def save_image_with_limit(image, directory, folder_name, cam_id, limit=300):
    os.makedirs(directory, exist_ok=True)
    image_files = glob.glob(os.path.join(directory, "*.jpg")) + glob.glob(os.path.join(directory, "*.png"))
    if len(image_files) >= limit:
        os.remove(min(image_files, key=os.path.getctime))
    timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    image_path = os.path.join(directory, f"{folder_name}_cam{cam_id}_{timestamp}.png")
    cv2.imwrite(image_path, image)
    return image_path


def image2base64(image):
    image = cv2.resize(image, (250, 150))
    success, buffer = cv2.imencode(".jpg", image)
    if not success:
        raise ValueError("Failed to encode image")
    return base64.b64encode(buffer).decode("utf-8")


def limit_openvino_threads(inference_threads):
    if inference_threads <= 0:
        return
    import openvino as ov

    original_compile_model = ov.Core.compile_model
    if getattr(original_compile_model, "_gantry_intrusion_patched", False):
        return

    def compile_model(self, model, device_name=None, config=None, *args, **kwargs):
        config = dict(config or {})
        config["INFERENCE_NUM_THREADS"] = inference_threads
        if device_name == "AUTO":
            device_name = "CPU"
        return original_compile_model(self, model, device_name=device_name, config=config, *args, **kwargs)

    compile_model._gantry_intrusion_patched = True
    ov.Core.compile_model = compile_model


def denormalized_points(points, width, height):
    denorm = []
    for x, y in points or []:
        if -1.0 <= x <= 1.0 and -1.0 <= y <= 1.0:
            x *= width
            y *= height
        point = (int(round(x)), int(round(y)))
        if not denorm or denorm[-1] != point:
            denorm.append(point)
    return denorm


def read_legacy_area_file(file_path):
    file_path = Path(file_path)
    if not file_path.exists():
        return []
    points = []
    with open(file_path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            x, y = map(int, line.split(","))
            point = (x, y)
            if not points or points[-1] != point:
                points.append(point)
    return points


def polygon_from_points(points, source):
    if len(points) < 3:
        raise ValueError(f"{source} needs at least 3 danger-zone points.")

    polygon = Polygon(points)
    if not polygon.is_valid:
        fixed = make_valid(polygon) if make_valid else polygon.buffer(0)
        if fixed.geom_type == "GeometryCollection":
            polygons_only = [geom for geom in fixed.geoms if geom.geom_type in ("Polygon", "MultiPolygon")]
            fixed = unary_union(polygons_only) if polygons_only else fixed
        if not fixed.is_empty and fixed.is_valid and fixed.geom_type in ("Polygon", "MultiPolygon"):
            polygon = fixed
            log.warning("%s polygon invalid; repaired for runtime use.", source)
        else:
            raise ValueError(f"{source} polygon invalid and cannot be repaired.")
    return polygon


def read_camera_danger_zone(config, camera, frame_width, frame_height, required=True, log_missing=True):
    regions = config.get("zones", {}).get("regions", {})
    cam_id = camera["id"]
    points = denormalized_points(regions.get(cam_id), frame_width, frame_height)
    source = f"config.json zones.regions.{cam_id}"
    if not points:
        legacy_path = PROJECT_DIR / "mask" / f"{cam_id}.txt"
        points = read_legacy_area_file(legacy_path)
        source = str(legacy_path)
    if not points:
        message = f"Missing danger zone for camera {cam_id}. Run tools/calibrate_zone.py {cam_id}"
        if required:
            log.error(message)
            sys.exit(1)
        if log_missing:
            log.warning(message)
        return None
    try:
        return polygon_from_points(points, source)
    except ValueError as e:
        if required:
            log.error("%s", e)
            sys.exit(1)
        log.warning("%s", e)
        return None


def read_danger_zones(config, cameras, frame_width, frame_height, required=True):
    polygons = []
    for camera in cameras:
        polygons.append(read_camera_danger_zone(config, camera, frame_width, frame_height, required=required))
    return polygons


def maybe_reload_danger_zone(cam_config, danger_zone, frame_width, frame_height, last_reload_time, reload_seconds=5):
    now = time.time()
    if now - last_reload_time < reload_seconds:
        return danger_zone, last_reload_time

    last_reload_time = now
    try:
        config = load_config()
        reloaded_zone = read_camera_danger_zone(
            config,
            cam_config,
            frame_width,
            frame_height,
            required=False,
            log_missing=False,
        )
    except Exception as e:
        log.warning("[%s] Failed to reload danger zone: %s", cam_config["id"], e)
        return danger_zone, last_reload_time

    if reloaded_zone is None:
        if danger_zone is not None:
            log.warning("[%s] Danger zone removed; display only until zone is configured.", cam_config["id"])
        return None, last_reload_time

    if danger_zone is None or not danger_zone.equals_exact(reloaded_zone, tolerance=0.01):
        log.info("[%s] Danger zone loaded/reloaded.", cam_config["id"])
    return reloaded_zone, last_reload_time


def bbox_in_danger_zone(danger_area_polygon, bbox, min_overlap_ratio=0.15, bottom_check_enabled=False, bottom_margin_ratio=0.1):
    bbox_poly = box(*bbox)
    try:
        if not danger_area_polygon.intersects(bbox_poly):
            return False
        intersection = danger_area_polygon.intersection(bbox_poly)
    except GEOSException as e:
        log.warning("Invalid danger zone geometry skipped for bbox: %s", e)
        return False

    bbox_area = bbox_poly.area
    if bbox_area <= 0:
        return False
    if intersection.area / bbox_area <= min_overlap_ratio:
        return False

    if bottom_check_enabled:
        _, _, _, y2 = bbox
        bbox_height = bbox[3] - bbox[1]
        try:
            _, _, _, inter_maxy = intersection.bounds
            if inter_maxy < y2 - (bbox_height * bottom_margin_ratio):
                return False
        except Exception:
            return False

    return True


def bbox_touches_danger_zone(danger_area_polygon, bbox, mode="bottom_line", line_width_ratio=0.8, bottom_offset_ratio=0.0):
    x1, y1, x2, y2 = bbox
    width = x2 - x1
    height = y2 - y1
    if width <= 0 or height <= 0:
        return False

    y = y2 - (height * bottom_offset_ratio)
    if mode == "bottom_center":
        shape = Point((x1 + x2) / 2.0, y)
    else:
        ratio = min(1.0, max(0.0, float(line_width_ratio)))
        margin = width * (1.0 - ratio) / 2.0
        shape = LineString([(x1 + margin, y), (x2 - margin, y)])

    try:
        return danger_area_polygon.intersects(shape) or danger_area_polygon.contains(shape)
    except GEOSException as e:
        log.warning("Invalid danger zone geometry skipped for contact check: %s", e)
        return False


def bbox_matches_danger_zone(danger_area_polygon, bbox, danger_filter):
    if danger_filter.get("mode", "bottom_line") in ("bottom_line", "bottom_center"):
        return bbox_touches_danger_zone(
            danger_area_polygon,
            bbox,
            mode=danger_filter.get("mode", "bottom_line"),
            line_width_ratio=float(danger_filter.get("line_width_ratio", 0.8)),
            bottom_offset_ratio=float(danger_filter.get("bottom_offset_ratio", 0.0)),
        )

    return bbox_in_danger_zone(
        danger_area_polygon,
        bbox,
        min_overlap_ratio=float(danger_filter.get("min_bbox_overlap_ratio", 0.15)),
        bottom_check_enabled=bool(danger_filter.get("bottom_check_enabled", False)),
        bottom_margin_ratio=float(danger_filter.get("bottom_margin_ratio", 0.1)),
    )


def calculate_overlap_ratio(bbox1, bbox2):
    x1_1, y1_1, x2_1, y2_1 = bbox1
    x1_2, y1_2, x2_2, y2_2 = bbox2
    inter_x1 = max(x1_1, x1_2)
    inter_y1 = max(y1_1, y1_2)
    inter_x2 = min(x2_1, x2_2)
    inter_y2 = min(y2_1, y2_2)
    if inter_x1 >= inter_x2 or inter_y1 >= inter_y2:
        return 0.0
    intersection_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
    bbox1_area = (x2_1 - x1_1) * (y2_1 - y1_1)
    return intersection_area / bbox1_area if bbox1_area else 0.0


def bbox_area(bbox):
    width = max(0.0, bbox[2] - bbox[0])
    height = max(0.0, bbox[3] - bbox[1])
    return width * height


def calculate_min_overlap_ratio(bbox1, bbox2):
    x1_1, y1_1, x2_1, y2_1 = bbox1
    x1_2, y1_2, x2_2, y2_2 = bbox2
    inter_x1 = max(x1_1, x1_2)
    inter_y1 = max(y1_1, y1_2)
    inter_x2 = min(x2_1, x2_2)
    inter_y2 = min(y2_1, y2_2)
    if inter_x1 >= inter_x2 or inter_y1 >= inter_y2:
        return 0.0
    min_area = min(bbox_area(bbox1), bbox_area(bbox2))
    if min_area <= 0:
        return 0.0
    return ((inter_x2 - inter_x1) * (inter_y2 - inter_y1)) / min_area


def deduplicate_overlapping_detections(bboxes, labels, confidences, duplicate_config):
    if not duplicate_config.get("enabled", False):
        return bboxes, labels, confidences

    max_overlap_ratio = float(duplicate_config.get("max_overlap_ratio", 0.8))
    kept = []
    for index in sorted(range(len(bboxes)), key=lambda i: confidences[i], reverse=True):
        label = normalize_class_label(labels[index])
        if any(
            label == normalize_class_label(labels[kept_index])
            and calculate_min_overlap_ratio(bboxes[index], bboxes[kept_index]) > max_overlap_ratio
            for kept_index in kept
        ):
            continue
        kept.append(index)

    kept.sort()
    return [bboxes[i] for i in kept], [labels[i] for i in kept], [confidences[i] for i in kept]


def draw_transparent_polygon(image, points, color=(0, 0, 255), opacity=0.3):
    overlay = image.copy()
    output = image.copy()
    if points is None:
        return image
    if hasattr(points, "geoms"):
        for geom in points.geoms:
            if geom.geom_type == "Polygon":
                cv2.fillPoly(overlay, [np.array(geom.exterior.coords, dtype=np.int32)], color)
        cv2.addWeighted(overlay, opacity, output, 1 - opacity, 0, output)
        return output
    if hasattr(points, "exterior"):
        points = points.exterior
    if hasattr(points, "coords"):
        points = list(points.coords)
    if len(points) > 0:
        cv2.fillPoly(overlay, [np.array(points, dtype=np.int32)], color)
        cv2.addWeighted(overlay, opacity, output, 1 - opacity, 0, output)
    return output


def draw_detection_boxes(image, bboxes, labels, confidences, color=(0, 255, 0)):
    output = image.copy()
    for bbox, label, conf in zip(bboxes, labels, confidences):
        x1, y1, x2, y2 = [int(v) for v in bbox]
        cv2.rectangle(output, (x1, y1), (x2, y2), color, 2)
        text = f"{label} {conf:.2f}"
        cv2.putText(output, text, (x1, max(24, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    return output


def alert_api(image, api, location):
    if not api:
        return
    url = api.rstrip("/") + "/alerts/intrusion_logs/"
    now = datetime.datetime.now(ZoneInfo("Asia/Taipei"))
    payload = {"image": str(image), "location": location, "timestamp": str(now), "status": "not_success"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        log.info("API Status Code: %s", response.status_code)
    except Exception as e:
        log.error("Error during API call: %s", e)


def handle_alert_in_background(annotated_frame, cam_id, api_url, alert_device_ip, location_id, raw_frame=None, debug_info=None):
    log.info("[%s] Background alert thread started.", cam_id)

    if alert_device_ip:
        try:
            requests.get(f"http://{alert_device_ip}:1880/gpio_out?pin=12&st=1", timeout=2)
            time.sleep(5)
            requests.get(f"http://{alert_device_ip}:1880/gpio_out?pin=12&st=0", timeout=2)
            log.info("[%s] Alarm cycle completed.", cam_id)
        except requests.exceptions.RequestException as e:
            log.error("[%s] Failed to trigger alarm: %s", cam_id, e)

    current_date = datetime.datetime.now().strftime("%Y%m%d")
    directory = IMG_LOG_DIR / current_date
    file_path = save_image_with_limit(annotated_frame, directory, "detected", cam_id)

    if file_path and raw_frame is not None and debug_info is not None:
        try:
            debug_dir = os.path.join(directory, "debug")
            os.makedirs(debug_dir, exist_ok=True)
            basename = os.path.splitext(os.path.basename(file_path))[0]
            raw_image_path = os.path.join(debug_dir, f"{basename}_raw.png")
            cv2.imwrite(raw_image_path, raw_frame)
            json_path = os.path.join(debug_dir, f"{basename}.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(debug_info, f, ensure_ascii=False, indent=4)
        except Exception as e:
            log.error("[%s] Error saving debug info: %s", cam_id, e)

    if file_path and os.path.exists(file_path):
        try:
            alert_image = cv2.imread(file_path)
            if alert_image is not None:
                alert_api(image2base64(alert_image), api_url, location_id)
        except Exception as e:
            log.error("[%s] Error processing saved image for API: %s", cam_id, e)


def resolve_model_source(model_config):
    if model_config.get("_resolved_model_source"):
        return model_config["_resolved_model_source"], bool(model_config.get("_resolved_is_openvino", False))

    openvino_path = project_path(model_config.get("openvino_path"))
    if model_config.get("prefer_openvino", True) and openvino_model_ready(openvino_path):
        return str(openvino_path), True
    if model_config.get("prefer_openvino", True) and openvino_path and openvino_path.exists():
        log.warning("OpenVINO path exists but is incomplete: %s", openvino_path)

    local_path = project_path(model_config.get("local_path"))
    if local_path and local_path.exists():
        return str(local_path), False

    repo_id = model_config.get("repo_id")
    filename = model_config.get("filename")
    if not repo_id or not filename:
        raise ValueError("model.repo_id/model.filename or model.local_path is required")

    path = hf_hub_download(repo_id=repo_id, filename=filename)
    return path, False


def openvino_model_ready(path):
    if not path or not path.is_dir():
        return False
    xml_files = list(path.glob("*.xml"))
    if not xml_files:
        return False
    weights_path = xml_files[0].with_suffix(".bin")
    if not weights_path.exists():
        return False
    try:
        import openvino as ov

        ov.Core().read_model(str(xml_files[0]), weights=str(weights_path))
    except Exception:
        return False
    return True


def maybe_export_openvino(model, model_source, model_config):
    openvino_path = project_path(model_config.get("openvino_path"))
    if not model_config.get("auto_export_openvino", False) or not openvino_path:
        return model_source
    if openvino_model_ready(openvino_path):
        return str(openvino_path)

    exported = model.export(format="openvino", imgsz=int(model_config.get("imgsz", 640)), device="cpu")
    exported_path = Path(exported)
    if not openvino_model_ready(exported_path):
        raise RuntimeError(f"OpenVINO export failed or is incomplete: {exported_path}")
    if exported_path.resolve() != openvino_path.resolve():
        openvino_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(exported_path, openvino_path, dirs_exist_ok=True)
        log.info("OpenVINO exported to %s", openvino_path)
    return str(openvino_path)


def load_model(model_config, inference_threads):
    model_source, is_openvino = resolve_model_source(model_config)
    limit_openvino_threads(inference_threads)
    model = YOLO(model_source)

    if not is_openvino and model_config.get("auto_export_openvino", False):
        exported_source = maybe_export_openvino(model, model_source, model_config)
        if exported_source != model_source:
            model_source = exported_source
            is_openvino = Path(model_source).is_dir()
            model = YOLO(model_source)

    names = normalized_names(model)
    log.info("Model loaded: %s", model_source)
    log.info("Model classes: %s", ", ".join(f"{idx}:{name}" for idx, name in names.items()))
    return model, names, is_openvino


def prepare_model_source(model_config, inference_threads):
    model_source, is_openvino = resolve_model_source(model_config)
    if is_openvino or not model_config.get("auto_export_openvino", False):
        return model_source, is_openvino
    limit_openvino_threads(inference_threads)
    exported_source = maybe_export_openvino(YOLO(model_source), model_source, model_config)
    return exported_source, openvino_model_ready(Path(exported_source))


def normalized_names(model):
    names = getattr(model, "names", {}) or {}
    if isinstance(names, list):
        return {idx: name for idx, name in enumerate(names)}
    return {int(idx): str(name) for idx, name in names.items()}


def warn_unknown_classes(names, class_config):
    available = normalized_class_set(names.values())
    for key in ("intrusion", "ignore", "mask"):
        missing = sorted(label for label in class_config.get(key, []) if normalize_class_label(label) not in available)
        if missing:
            log.warning("Configured classes not in model.%s: %s", key, ", ".join(missing))


def class_name(names, class_id):
    return names.get(int(class_id), str(int(class_id)))


def normalize_class_label(label):
    return str(label).strip().casefold()


def normalized_class_set(labels):
    return {normalize_class_label(label) for label in labels}


def configured_min_confidence(label, filter_config):
    normalized_label = normalize_class_label(label)
    for configured_label, min_conf in filter_config.get("min_confidence_by_class", {}).items():
        if normalize_class_label(configured_label) == normalized_label:
            return float(min_conf)
    return 0.0


def xyxy_list(box_item):
    return [float(x) for x in box_item.xyxy[0]]


def passes_class_and_filter(bbox, class_label, conf, frame_shape, class_config, filter_config):
    normalized_label = normalize_class_label(class_label)
    if normalized_label in normalized_class_set(class_config.get("ignore", [])):
        return False

    intrusion_classes = normalized_class_set(class_config.get("intrusion", []))
    if intrusion_classes and normalized_label not in intrusion_classes:
        return False

    min_conf = configured_min_confidence(class_label, filter_config)
    if conf < min_conf:
        return False

    frame_height, frame_width = frame_shape[:2]
    box_width = bbox[2] - bbox[0]
    box_height = bbox[3] - bbox[1]

    max_size = filter_config.get("max_bbox_size", {})
    if max_size.get("enabled", False):
        if box_width > frame_width * float(max_size.get("width_ratio", 1.0)):
            return False
        if box_height > frame_height * float(max_size.get("height_ratio", 1.0)):
            return False

    edge = filter_config.get("edge_confidence", {})
    if edge.get("enabled", False):
        center_x = (bbox[0] + bbox[2]) / 2.0
        edge_ratio = float(edge.get("edge_ratio", 0.1))
        if center_x <= frame_width * edge_ratio or center_x >= frame_width * (1.0 - edge_ratio):
            if conf < float(edge.get("min_confidence", 0.75)):
                return False

    return True


def prediction_device(model_config, is_openvino):
    device = model_config.get("device", "")
    if not device:
        return None
    if is_openvino:
        return device
    return "cpu" if str(device).startswith("intel:") else device


def camera_process_worker(
    cam_config,
    danger_zone,
    display_queue,
    stop_event,
    api_url,
    enable_recording,
    cooldown_seconds,
    runtime_config,
    model_config,
    class_config,
    filter_config,
):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)

    cam_id = cam_config["id"]
    rtsp_link = cam_config["rtsp_url"]
    alert_device_ip = cam_config.get("alert_device_ip")
    location_id = cam_config.get("location_id")

    frame_width = int(runtime_config.get("frame_width", 1280))
    frame_height = int(runtime_config.get("frame_height", 720))
    inference_fps = float(runtime_config.get("inference_fps", 4))
    inference_threads = int(runtime_config.get("inference_threads", 2))
    record_width = int(runtime_config.get("record_width", 1920))
    record_height = int(runtime_config.get("record_height", 1080))
    record_fps = float(runtime_config.get("record_fps", 15))

    log.info("[%s] Process started. Connecting RTSP...", cam_id)
    transports = ("tcp", "udp")
    transport_index = 0
    cam = Camera(rtsp_link, transports[transport_index], width=frame_width, height=frame_height)

    preview_deadline = time.time() + 5
    while not stop_event.is_set() and time.time() < preview_deadline:
        frame = cam.get_data()
        if frame is not None:
            preview_frame = cv2.resize(frame, (frame_width, frame_height))
            preview_frame = draw_transparent_polygon(preview_frame, danger_zone)
            if not display_queue.full():
                display_queue.put((cam_id, preview_frame))
            break
        time.sleep(0.1)

    log.info("[%s] RTSP ready. Loading model...", cam_id)
    model, names, is_openvino = load_model(model_config, inference_threads)
    warn_unknown_classes(names, class_config)
    device = prediction_device(model_config, is_openvino)
    last_zone_reload_time = time.time()

    last_alert_time = 0
    frame_interval = 1.0 / inference_fps if inference_fps > 0 else 0
    no_frame_counter = 0
    no_frame_sleep = 0.2
    reconnect_after_seconds = 60
    first_no_frame_time = None
    last_no_frame_log = 0
    video_writer = None
    current_record_hour = None
    record_dir = "./records"

    if enable_recording:
        os.makedirs(record_dir, exist_ok=True)

    mask_history_bboxes = []
    mask_history_ttl = 0
    mask_overlap = filter_config.get("mask_overlap", {})
    mask_classes = normalized_class_set(class_config.get("mask", []))
    mask_ttl_frames = int(mask_overlap.get("ttl_frames", 0))

    try:
        while not stop_event.is_set():
            try:
                now = datetime.datetime.now(ZoneInfo("Asia/Taipei"))
                t_start = time.time()
                frame = cam.get_data()

                if frame is None:
                    if not cam.is_opened():
                        transport_index = (transport_index + 1) % len(transports)
                        log.warning("[%s] RTSP not open. Reconnecting via %s in 5 seconds.", cam_id, transports[transport_index])
                        cam.release()
                        time.sleep(5)
                        cam = Camera(rtsp_link, transports[transport_index], width=frame_width, height=frame_height)
                        no_frame_counter = 0
                        first_no_frame_time = None
                        last_no_frame_log = 0
                        continue

                    no_frame_counter += 1
                    now_ts = time.time()
                    if first_no_frame_time is None:
                        first_no_frame_time = now_ts
                    elapsed_no_frame = now_ts - first_no_frame_time
                    remaining = max(0, int(reconnect_after_seconds - elapsed_no_frame))
                    if no_frame_counter == 1 or now_ts - last_no_frame_log >= 15:
                        log.warning("[%s] Waiting for RTSP frame. Reconnect in %s seconds.", cam_id, remaining)
                        last_no_frame_log = now_ts

                    if elapsed_no_frame >= reconnect_after_seconds:
                        transport_index = (transport_index + 1) % len(transports)
                        log.error("[%s] No frame for %s seconds. Reconnecting via %s.", cam_id, reconnect_after_seconds, transports[transport_index])
                        cam.release()
                        time.sleep(0.5)
                        cam = Camera(rtsp_link, transports[transport_index], width=frame_width, height=frame_height)
                        no_frame_counter = 0
                        first_no_frame_time = None
                        last_no_frame_log = 0

                    time.sleep(no_frame_sleep)
                    continue

                if no_frame_counter:
                    log.info("[%s] RTSP frame recovered (%s).", cam_id, transports[transport_index])
                no_frame_counter = 0
                first_no_frame_time = None
                last_no_frame_log = 0

                frame = cv2.resize(frame, (frame_width, frame_height))
                danger_zone, last_zone_reload_time = maybe_reload_danger_zone(
                    cam_config,
                    danger_zone,
                    frame_width,
                    frame_height,
                    last_zone_reload_time,
                )
                predict_args = {
                    "source": frame,
                    "iou": float(model_config.get("iou", 0.5)),
                    "conf": float(model_config.get("confidence", 0.25)),
                    "imgsz": int(model_config.get("imgsz", 640)),
                    "verbose": False,
                }
                if device:
                    predict_args["device"] = device
                results = model(**predict_args)[0]

                current_mask_bboxes = [
                    xyxy_list(result)
                    for result in results.boxes
                    if normalize_class_label(class_name(names, int(result.cls[0]))) in mask_classes
                ]
                if current_mask_bboxes:
                    mask_history_bboxes = current_mask_bboxes
                    mask_history_ttl = mask_ttl_frames
                elif mask_history_ttl > 0:
                    mask_history_ttl -= 1
                else:
                    mask_history_bboxes = []

                active_mask_bboxes = mask_history_bboxes if mask_overlap.get("enabled", False) else []
                candidate_bboxes = []
                candidate_labels = []
                candidate_confidences = []

                for result in results.boxes:
                    bbox = xyxy_list(result)
                    cls = int(result.cls[0])
                    conf = float(result.conf[0])
                    label = class_name(names, cls)

                    if not passes_class_and_filter(bbox, label, conf, frame.shape, class_config, filter_config):
                        continue

                    if active_mask_bboxes and any(
                        calculate_overlap_ratio(bbox, mask_bbox) > float(mask_overlap.get("max_overlap_ratio", 0.8))
                        for mask_bbox in active_mask_bboxes
                    ):
                        continue

                    candidate_bboxes.append(bbox)
                    candidate_labels.append(label)
                    candidate_confidences.append(conf)

                duplicate_config = filter_config.get("duplicate_bbox", {})
                candidate_bboxes, candidate_labels, candidate_confidences = deduplicate_overlapping_detections(
                    candidate_bboxes,
                    candidate_labels,
                    candidate_confidences,
                    duplicate_config,
                )

                danger_filter = filter_config.get("danger_zone_overlap", {})
                intrusion_bboxes = []
                if danger_zone is not None:
                    intrusion_bboxes = [
                        bbox
                        for bbox in candidate_bboxes
                        if bbox_matches_danger_zone(danger_zone, bbox, danger_filter)
                    ]

                is_intrusion = bool(intrusion_bboxes)
                current_time = time.time()
                is_in_cooldown = (current_time - last_alert_time) <= cooldown_seconds

                if is_intrusion and not is_in_cooldown:
                    last_alert_time = current_time
                    annotated_frame_for_alert = draw_detection_boxes(
                        frame, candidate_bboxes, candidate_labels, candidate_confidences, color=(0, 255, 255)
                    )
                    annotated_frame_for_alert = draw_transparent_polygon(annotated_frame_for_alert, danger_zone)
                    debug_info = {
                        "cam_id": cam_id,
                        "timestamp": now.isoformat(),
                        "model_classes": names,
                        "bboxes": [xyxy_list(box_item) for box_item in results.boxes],
                        "confidences": [float(box_item.conf[0]) for box_item in results.boxes],
                        "classes": [int(box_item.cls[0]) for box_item in results.boxes],
                        "candidate_labels": candidate_labels,
                        "candidate_confidences": candidate_confidences,
                        "candidate_bboxes": candidate_bboxes,
                        "final_intrusion_bboxes": intrusion_bboxes,
                    }
                    alert_thread = threading.Thread(
                        target=handle_alert_in_background,
                        args=(annotated_frame_for_alert, cam_id, api_url, alert_device_ip, location_id, frame.copy(), debug_info),
                        daemon=True,
                    )
                    alert_thread.start()

                display_frame = draw_detection_boxes(frame, candidate_bboxes, candidate_labels, candidate_confidences)
                final_display_frame = draw_transparent_polygon(display_frame, danger_zone)
                if not display_queue.full():
                    display_queue.put((cam_id, final_display_frame))

                if enable_recording:
                    current_hour = now.hour
                    if video_writer is not None and current_record_hour != current_hour:
                        video_writer.release()
                        video_writer = None
                        log.info("[%s] Rotated hourly recording.", cam_id)

                    if video_writer is None:
                        timestamp = time.strftime("%Y%m%d_%H%M%S")
                        record_path = os.path.join(record_dir, f"record_cam{cam_id}_{timestamp}.mp4")
                        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                        video_writer = cv2.VideoWriter(record_path, fourcc, record_fps, (record_width, record_height))
                        current_record_hour = current_hour
                        log.info("[%s] Started recording: %s", cam_id, record_path)

                    record_frame = cv2.resize(final_display_frame, (record_width, record_height))
                    video_writer.write(record_frame)

                if frame_interval:
                    time.sleep(max(0, frame_interval - (time.time() - t_start)))

            except Exception as e:
                log.error("[%s] Unhandled exception in worker process: %s", cam_id, e, exc_info=True)
                time.sleep(5)
    finally:
        if video_writer is not None:
            video_writer.release()
        cam.release()


def main():
    config = load_config()
    api_url = config.get("api_url", "")
    enable_recording = bool(config.get("enable_recording", False))
    cooldown_seconds = float(config.get("cooldown_seconds", 5))
    display_enabled = bool(config.get("display", {}).get("enabled", True))
    runtime_config = config.get("runtime", {})
    model_config = dict(config.get("model", {}))
    class_config = config.get("classes", {})
    filter_config = config.get("filters", {})
    cameras = config.get("cameras", [])

    if not cameras:
        log.error("No cameras configured.")
        sys.exit(1)

    cleanup_runtime_outputs()

    active_camera_ids = [cam["id"] for cam in cameras]
    frame_width = int(runtime_config.get("frame_width", 1280))
    frame_height = int(runtime_config.get("frame_height", 720))
    danger_zones = read_danger_zones(config, cameras, frame_width, frame_height, required=False)
    model_source, is_openvino = prepare_model_source(model_config, int(runtime_config.get("inference_threads", 0)))
    model_config["_resolved_model_source"] = model_source
    model_config["_resolved_is_openvino"] = is_openvino

    display_queue = Queue(maxsize=len(cameras) * 2)
    stop_event = Event()
    install_shutdown_handlers(stop_event)

    log.info("Recording: %s", "enabled" if enable_recording else "disabled")
    log.info("Display: %s", "enabled" if display_enabled else "disabled")

    processes = []
    for i, cam in enumerate(cameras):
        process = Process(
            target=camera_process_worker,
            args=(
                cam,
                danger_zones[i],
                display_queue,
                stop_event,
                api_url,
                enable_recording,
                cooldown_seconds,
                runtime_config,
                model_config,
                class_config,
                filter_config,
            ),
            daemon=True,
        )
        processes.append(process)
        process.start()
        time.sleep(2)

    latest_frames = {}
    for cam_id in active_camera_ids:
        frame = np.zeros((frame_height, frame_width, 3), dtype=np.uint8)
        cv2.putText(frame, f"Waiting for {cam_id}", (40, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (200, 200, 200), 2)
        latest_frames[cam_id] = frame
    window_names = {cam_id: f"Camera {cam_id}" for cam_id in active_camera_ids}

    try:
        last_cleanup_time = 0
        while not stop_event.is_set():
            if time.time() - last_cleanup_time >= 3600:
                cleanup_runtime_outputs()
                last_cleanup_time = time.time()

            while not display_queue.empty():
                try:
                    cam_id, frame = display_queue.get_nowait()
                    latest_frames[cam_id] = frame
                except Exception:
                    break

            if display_enabled:
                for cam_id, frame in latest_frames.items():
                    cv2.imshow(window_names[cam_id], frame)

                key = cv2.waitKey(1) & 0xFF
                if key in [ord("q"), ord("Q")]:
                    log.info("Quit signal received. Shutting down.")
                    stop_event.set()
                    break
                if key in [ord("s"), ord("S")]:
                    save_dir = "./exhibition_shots"
                    os.makedirs(save_dir, exist_ok=True)
                    timestamp = time.strftime("%Y%m%d_%H%M%S")
                    for c_id, frame in latest_frames.items():
                        filename = os.path.join(save_dir, f"exhibition_cam{c_id}_{timestamp}.jpg")
                        cv2.imwrite(filename, frame)
                    log.info("Screenshots saved to %s.", save_dir)

            time.sleep(0.01)

    except KeyboardInterrupt:
        log.info("Keyboard interrupt received. Shutting down.")
        stop_event.set()

    finally:
        cleanup_processes(processes)

        if display_enabled:
            cv2.destroyAllWindows()
        log.info("Shutdown complete.")


if __name__ == "__main__":
    main()
