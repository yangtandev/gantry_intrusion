import cv2
import numpy as np
import threading
import time
import logging as log
import os
import subprocess


def frame_quality_metrics(frame, max_side=320):
    if frame is None or frame.ndim != 3 or frame.shape[2] != 3:
        return {"grayish_ratio": 1.0, "low_sat_ratio": 1.0, "laplacian_var": 0.0, "edge_density": 0.0}

    height, width = frame.shape[:2]
    scale = min(1.0, max_side / max(height, width))
    sample = frame
    if scale < 1.0:
        sample = cv2.resize(frame, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)

    hsv = cv2.cvtColor(sample, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]
    gray_delta = sample.max(axis=2) - sample.min(axis=2)
    grayish = (gray_delta <= 12) & (val >= 35) & (val <= 230)
    gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)
    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    edge_density = (cv2.Canny(gray, 50, 150) > 0).mean()
    return {
        "grayish_ratio": float(grayish.mean()),
        "low_sat_ratio": float((sat <= 28).mean()),
        "laplacian_var": float(laplacian_var),
        "edge_density": float(edge_density),
    }


def is_bad_frame(frame):
    metrics = frame_quality_metrics(frame)
    return (
        metrics["grayish_ratio"] >= 0.90
        and metrics["low_sat_ratio"] >= 0.90
        and metrics["laplacian_var"] <= 300.0
        and metrics["edge_density"] <= 0.04
    )


class Camera:
    def __init__(
        self,
        rtsp,
        transport='tcp',
        width=1280,
        height=720,
        reject_bad_frames=True,
    ):
        self.rtsp = rtsp
        self.transport = transport
        self.width = width
        self.height = height
        self.reject_bad_frames = reject_bad_frames
        self.stopped = False
        self.ret = False
        self.frame = None
        self.bad_frame_count = 0
        self.process = None
        self.stream = None

        if self.rtsp.startswith('rtsp://'):
            self._open_ffmpeg()
        else:
            self._open_opencv()

    def _open_opencv(self):
        self.stream = cv2.VideoCapture(self.rtsp)
        if not self.stream.isOpened():
            log.error(f"CAM {self.rtsp} [ACQ]: 無法開啟影像來源。")
        else:
            ret, frame = self.stream.read()
            self._accept_frame(ret, frame)
            self.thread = threading.Thread(target=self._update, daemon=True)
            self.thread.start()

    def _open_ffmpeg(self):
        cmd = [
            'ffmpeg',
            '-hide_banner',
            '-loglevel', 'error',
            '-fflags', 'nobuffer+discardcorrupt',
            '-flags', 'low_delay',
            '-rtsp_transport', self.transport,
            *(['-rtsp_flags', 'prefer_tcp'] if self.transport == 'tcp' else []),
            '-i', self.rtsp,
            '-an',
            '-vf', f'scale={self.width}:{self.height}',
            '-pix_fmt', 'bgr24',
            '-f', 'rawvideo',
            'pipe:1',
        ]
        self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**8)
        self.thread = threading.Thread(target=self._update_ffmpeg, daemon=True)
        self.thread.start()

    def _update(self):
        while not self.stopped:
            if not self.stream.isOpened():
                self.stopped = True
                break
            # 持續抓取最新畫面
            ret, frame = self.stream.read()
            self._accept_frame(ret, frame)
            time.sleep(0.01) # 略微休眠避免佔用過高 CPU

    def _update_ffmpeg(self):
        frame_size = self.width * self.height * 3
        while not self.stopped and self.process and self.process.poll() is None:
            raw = self.process.stdout.read(frame_size)
            if len(raw) != frame_size:
                self.ret = False
                break
            frame = np.frombuffer(raw, dtype=np.uint8).reshape((self.height, self.width, 3))
            self._accept_frame(True, frame)

    def _accept_frame(self, ret, frame):
        if not ret or frame is None:
            self.ret = False
            self.frame = None
            return

        if self.reject_bad_frames and is_bad_frame(frame):
            self.bad_frame_count += 1
            self.ret = False
            self.frame = None
            if self.bad_frame_count == 1 or self.bad_frame_count % 300 == 0:
                metrics = frame_quality_metrics(frame)
                log.warning(
                    "CAM %s [ACQ]: bad gray-noise frame dropped (grayish=%.3f low_sat=%.3f lap=%.1f edge=%.3f count=%s).",
                    self.rtsp,
                    metrics["grayish_ratio"],
                    metrics["low_sat_ratio"],
                    metrics["laplacian_var"],
                    metrics["edge_density"],
                    self.bad_frame_count,
                )
            return

        self.ret = True
        self.frame = frame
        self.bad_frame_count = 0

    def get_data(self):
        # 回傳直接可供 OpenCV/YOLO 使用的 numpy array (BGR 格式)
        if self.ret and self.frame is not None:
            return self.frame.copy()
        return None

    def is_opened(self):
        if self.process is not None:
            return self.process.poll() is None
        return self.stream is not None and self.stream.isOpened()

    def release(self):
        self.stopped = True
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if self.stream is not None and self.stream.isOpened():
            self.stream.release()
        if hasattr(self, 'thread') and self.thread.is_alive():
            self.thread.join(timeout=2)
