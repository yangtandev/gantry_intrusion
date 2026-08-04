import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from camera import Camera

COLOR = (0, 0, 255)


def parse_args():
    parser = argparse.ArgumentParser(description="Capture or load one frame and draw one intrusion danger zone.")
    parser.add_argument("camera_id", nargs="?")
    parser.add_argument("--config", default=str(ROOT / "config.json"))
    parser.add_argument("--output", help="output config path. default: overwrite --config")
    parser.add_argument("--image", help="use an image file instead of grabbing the camera")
    parser.add_argument("--timeout", type=float, default=20.0)
    return parser.parse_args()


def load_config(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def camera_by_id(config, camera_id):
    cameras = config.get("cameras", [])
    if camera_id is None:
        if not cameras:
            raise ValueError("config has no cameras")
        return cameras[0]
    for camera in cameras:
        if camera.get("id") == camera_id:
            return camera
    raise ValueError(f"unknown camera: {camera_id}")


def grab_frame(camera, runtime, timeout):
    width = int(runtime.get("frame_width", 1280))
    height = int(runtime.get("frame_height", 720))
    capture = Camera(camera["rtsp_url"], "tcp", width=width, height=height)
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            frame = capture.get_data()
            if frame is not None:
                return cv2.resize(frame, (width, height))
            time.sleep(0.1)
    finally:
        capture.release()
    raise TimeoutError(f"no frame from {camera['id']} within {timeout:g}s")


def normalized(points, width, height):
    return [[round(x / width, 4), round(y / height, 4)] for x, y in points]


def denormalized(points, width, height):
    denorm = []
    for x, y in points or []:
        if -1.0 <= x <= 1.0 and -1.0 <= y <= 1.0:
            x *= width
            y *= height
        denorm.append((int(round(x)), int(round(y))))
    return denorm


def read_legacy_points(camera_id):
    path = ROOT / "mask" / f"{camera_id}.txt"
    if not path.exists():
        return []
    points = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        x, y = map(int, line.split(","))
        points.append((x, y))
    return points


def existing_points(config, camera_id, frame_shape):
    height, width = frame_shape[:2]
    points = config.get("zones", {}).get("regions", {}).get(camera_id)
    return denormalized(points, width, height) or read_legacy_points(camera_id)


def draw_preview(frame, points):
    preview = frame.copy()
    overlay = preview.copy()
    if len(points) >= 3:
        polygon = np.array(points, dtype=np.int32)
        cv2.fillPoly(overlay, [polygon], COLOR)
        cv2.polylines(preview, [polygon], True, COLOR, 3)
    for index, point in enumerate(points):
        cv2.circle(preview, point, 6, COLOR, -1)
        if index:
            cv2.line(preview, points[index - 1], point, COLOR, 2)
    if points:
        cv2.putText(preview, "Danger", points[0], cv2.FONT_HERSHEY_SIMPLEX, 1.1, COLOR, 3)
    cv2.addWeighted(overlay, 0.18, preview, 0.82, 0, preview)
    cv2.putText(
        preview,
        "left-click add | right-click or U undo | R reset | S save | Q quit",
        (16, 32),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        2,
    )
    return preview


def edit_zone(frame, points):
    window = "calibrate_intrusion_zone"

    def on_mouse(event, x, y, *_):
        if event == cv2.EVENT_LBUTTONDOWN:
            points.append((x, y))
        elif event == cv2.EVENT_RBUTTONDOWN and points:
            points.pop()

    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window, on_mouse)

    while True:
        cv2.imshow(window, draw_preview(frame, points))
        key = cv2.waitKey(30) & 0xFF
        if key in (ord("u"), ord("U"), 8) and points:
            points.pop()
        elif key in (ord("r"), ord("R")):
            points.clear()
        elif key in (ord("q"), ord("Q"), 27):
            cv2.destroyWindow(window)
            return None
        elif key in (ord("s"), ord("S")):
            if len(points) < 3:
                print("Need at least 3 points")
                continue
            cv2.destroyWindow(window)
            return points


def save_zone(config, config_path, output_path, camera_id, points, frame_shape):
    height, width = frame_shape[:2]
    regions = config.setdefault("zones", {}).setdefault("regions", {})
    regions[camera_id] = normalized(points, width, height)

    path = Path(output_path or config_path)
    with path.open("w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)
        f.write("\n")
    return path


def main():
    args = parse_args()
    config = load_config(args.config)
    camera = camera_by_id(config, args.camera_id)
    camera_id = camera["id"]
    runtime = config.get("runtime", {})
    width = int(runtime.get("frame_width", 1280))
    height = int(runtime.get("frame_height", 720))

    if args.image:
        frame = cv2.imread(args.image)
        if frame is None:
            raise FileNotFoundError(f"cannot read image: {args.image}")
        frame = cv2.resize(frame, (width, height))
    else:
        frame = grab_frame(camera, runtime, args.timeout)

    points = edit_zone(frame, existing_points(config, camera_id, frame.shape))
    if points is None:
        print("Canceled. Config unchanged.")
        return 1
    path = save_zone(config, args.config, args.output, camera_id, points, frame.shape)
    print(f"Saved {camera_id} zone to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
