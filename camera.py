import cv2
import numpy as np
import threading
import time
import logging as log
import os
import subprocess

class Camera:
    def __init__(self, rtsp, transport='tcp', width=1280, height=720):
        self.rtsp = rtsp
        self.transport = transport
        self.width = width
        self.height = height
        self.stopped = False
        self.ret = False
        self.frame = None
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
            self.ret, self.frame = self.stream.read()
            self.thread = threading.Thread(target=self._update, daemon=True)
            self.thread.start()

    def _open_ffmpeg(self):
        cmd = [
            'ffmpeg',
            '-hide_banner',
            '-loglevel', 'error',
            '-rtsp_transport', self.transport,
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
            self.ret, self.frame = self.stream.read()
            time.sleep(0.01) # 略微休眠避免佔用過高 CPU

    def _update_ffmpeg(self):
        frame_size = self.width * self.height * 3
        while not self.stopped and self.process and self.process.poll() is None:
            raw = self.process.stdout.read(frame_size)
            if len(raw) != frame_size:
                self.ret = False
                break
            self.frame = np.frombuffer(raw, dtype=np.uint8).reshape((self.height, self.width, 3))
            self.ret = True

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
