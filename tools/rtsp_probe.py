import json
import os
import sys
import time
from pathlib import Path

import cv2


def read_one(url, transport, timeout=10):
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = f"rtsp_transport;{transport}|stimeout;5000000"
    started = time.time()
    cap = cv2.VideoCapture(url)
    opened_at = time.time()
    opened = cap.isOpened()
    first_frame_at = None
    frame_shape = None

    while opened and time.time() - opened_at < timeout:
        ok, frame = cap.read()
        if ok and frame is not None:
            first_frame_at = time.time()
            frame_shape = frame.shape
            break
        time.sleep(0.1)

    cap.release()
    return {
        "transport": transport,
        "opened": opened,
        "open_sec": round(opened_at - started, 2),
        "first_frame_sec": None if first_frame_at is None else round(first_frame_at - started, 2),
        "frame_shape": frame_shape,
    }


def main():
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("config.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))

    for camera in config["cameras"]:
        print(f"\n[{camera['id']}] {camera['rtsp_url']}", flush=True)
        for transport in ("tcp", "udp"):
            result = read_one(camera["rtsp_url"], transport)
            print(result, flush=True)


if __name__ == "__main__":
    main()
