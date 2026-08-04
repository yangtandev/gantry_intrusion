import json
import argparse
import sys
import time
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from camera import Camera


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("camera_id", nargs="?")
    parser.add_argument("--output-dir", default=str(ROOT / "image"))
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser.parse_args()


def capture(camera, runtime, output_dir, timeout=10):
    width = int(runtime.get("frame_width", 1280))
    height = int(runtime.get("frame_height", 720))
    cam = Camera(camera["rtsp_url"], "tcp", width=width, height=height)
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            frame = cam.get_data()
            if frame is not None:
                output_dir.mkdir(parents=True, exist_ok=True)
                path = output_dir / f"{camera['id']}.jpg"
                cv2.imwrite(str(path), cv2.resize(frame, (width, height)))
                print(path)
                return True
            time.sleep(0.1)
    finally:
        cam.release()
    print(f"failed: {camera['id']}", file=sys.stderr)
    return False


def main():
    args = parse_args()
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    wanted_id = args.camera_id
    cameras = config["cameras"]
    if wanted_id:
        cameras = [camera for camera in cameras if camera["id"] == wanted_id]
        if not cameras:
            print(f"unknown camera: {wanted_id}", file=sys.stderr)
            sys.exit(1)

    ok = True
    for camera in cameras:
        ok = capture(camera, config.get("runtime", {}), Path(args.output_dir), timeout=args.timeout) and ok
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
