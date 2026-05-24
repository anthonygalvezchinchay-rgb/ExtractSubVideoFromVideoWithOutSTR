# modules/video_decoder.py
"""
Persistent, frame-exact video decoder for interactive subtitle authoring.

Supports two backends:
  1. PyAV (preferred) — FFmpeg-based, true frame-accurate seeking via PTS.
  2. OpenCV VideoCapture (fallback) — uses frame index positioning.

The decoder stays open for the lifetime of a session, enabling rapid
frame-by-frame navigation without re-opening the container.
"""

import os
import logging
from typing import Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Try importing PyAV at module level; fall back gracefully.
_HAS_PYAV = False
try:
    import av
    _HAS_PYAV = True
except ImportError:
    logger.info("PyAV not installed — falling back to OpenCV for frame decoding")


class VideoDecoder:
    """
    Persistent, random-access video frame decoder.

    Usage::

        decoder = VideoDecoder("/path/to/video.mp4")
        frame_bgr, timestamp = decoder.get_frame(120)
        decoder.close()
    """

    def __init__(self, video_path: str):
        if not os.path.isfile(video_path):
            raise FileNotFoundError(f"Video not found: {video_path}")

        self.video_path = video_path
        self._backend: str = "none"

        # Metadata — populated by whichever backend succeeds
        self.fps: float = 0.0
        self.total_frames: int = 0
        self.width: int = 0
        self.height: int = 0
        self.duration_sec: float = 0.0

        # PyAV handles
        self._av_container = None
        self._av_stream = None

        # OpenCV handle
        self._cv_cap: Optional[cv2.VideoCapture] = None

        self._open()

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def _open(self):
        """Open video with the best available backend."""
        if _HAS_PYAV:
            try:
                self._open_pyav()
                return
            except Exception as exc:
                logger.warning(f"PyAV failed to open video: {exc} — trying OpenCV")

        self._open_opencv()

    def _open_pyav(self):
        """Open video via PyAV."""
        container = av.open(self.video_path)
        stream = container.streams.video[0]
        # Enable multithreaded decoding for speed
        stream.thread_type = "AUTO"

        self._av_container = container
        self._av_stream = stream
        self._backend = "pyav"

        self.fps = float(stream.average_rate) if stream.average_rate else 30.0
        self.width = stream.width
        self.height = stream.height

        # Total frames: prefer the stream metadata, estimate from duration otherwise
        if stream.frames and stream.frames > 0:
            self.total_frames = stream.frames
        elif stream.duration and stream.time_base:
            self.duration_sec = float(stream.duration * stream.time_base)
            self.total_frames = int(self.duration_sec * self.fps)
        else:
            # Last resort: container-level duration
            if container.duration:
                self.duration_sec = container.duration / av.time_base
                self.total_frames = int(self.duration_sec * self.fps)
            else:
                self.total_frames = 0

        if self.duration_sec == 0.0 and self.total_frames > 0:
            self.duration_sec = self.total_frames / self.fps

        logger.info(
            f"Opened via PyAV: {self.width}x{self.height} "
            f"@ {self.fps:.2f} fps, {self.total_frames} frames"
        )

    def _open_opencv(self):
        """Open video via OpenCV VideoCapture."""
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {self.video_path}")

        self._cv_cap = cap
        self._backend = "opencv"

        self.fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.duration_sec = self.total_frames / self.fps if self.fps > 0 else 0.0

        logger.info(
            f"Opened via OpenCV: {self.width}x{self.height} "
            f"@ {self.fps:.2f} fps, {self.total_frames} frames"
        )

    def close(self):
        """Release all resources."""
        if self._av_container:
            try:
                self._av_container.close()
            except Exception:
                pass
            self._av_container = None
            self._av_stream = None

        if self._cv_cap:
            try:
                self._cv_cap.release()
            except Exception:
                pass
            self._cv_cap = None

        self._backend = "none"

    # ── Frame Access ───────────────────────────────────────────────────────

    def get_frame(self, frame_index: int) -> Tuple[np.ndarray, float]:
        """
        Decode and return a specific frame.

        Args:
            frame_index: Zero-based frame index.

        Returns:
            Tuple of (BGR numpy array, timestamp_seconds).

        Raises:
            RuntimeError: If the frame cannot be decoded.
        """
        frame_index = max(0, min(frame_index, self.total_frames - 1))

        if self._backend == "pyav":
            return self._get_frame_pyav(frame_index)
        elif self._backend == "opencv":
            return self._get_frame_opencv(frame_index)
        else:
            raise RuntimeError("Video decoder is not open")

    def _get_frame_pyav(self, frame_index: int) -> Tuple[np.ndarray, float]:
        """Frame-accurate seek + decode via PyAV."""
        stream = self._av_stream
        container = self._av_container
        time_base = stream.time_base

        # Calculate target PTS from frame index
        target_sec = frame_index / self.fps
        target_pts = int(target_sec / float(time_base))

        # Seek to the nearest keyframe BEFORE target_pts
        container.seek(target_pts, stream=stream)

        # Decode forward until reaching (or passing) the exact target frame
        for frame in container.decode(video=0):
            current_sec = float(frame.pts * time_base) if frame.pts is not None else 0.0
            current_idx = int(round(current_sec * self.fps))
            if current_idx >= frame_index:
                img = frame.to_ndarray(format="bgr24")
                return img, current_sec

        # Fallback if PyAV decode loop exhausts (e.g. near EOF)
        return self._get_frame_opencv_standalone(frame_index)

    def _get_frame_opencv(self, frame_index: int) -> Tuple[np.ndarray, float]:
        """Direct frame positioning via persistent OpenCV capture."""
        cap = self._cv_cap
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ret, frame = cap.read()
        if not ret or frame is None:
            raise RuntimeError(f"Could not decode frame {frame_index}")
        timestamp = frame_index / self.fps
        return frame, timestamp

    def _get_frame_opencv_standalone(self, frame_index: int) -> Tuple[np.ndarray, float]:
        """One-shot OpenCV fallback (opens/closes its own capture)."""
        cap = cv2.VideoCapture(self.video_path)
        try:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ret, frame = cap.read()
            if not ret or frame is None:
                raise RuntimeError(f"Could not decode frame {frame_index} (fallback)")
            return frame, frame_index / self.fps
        finally:
            cap.release()

    # ── Utilities ──────────────────────────────────────────────────────────

    def get_metadata(self) -> dict:
        """Return serialisable video metadata."""
        return {
            "backend": self._backend,
            "fps": round(self.fps, 3),
            "total_frames": self.total_frames,
            "width": self.width,
            "height": self.height,
            "duration_sec": round(self.duration_sec, 3),
        }

    def frame_to_timestamp(self, frame_index: int) -> float:
        """Convert frame index to timestamp in seconds."""
        return frame_index / self.fps if self.fps > 0 else 0.0

    def timestamp_to_frame(self, timestamp_sec: float) -> int:
        """Convert timestamp in seconds to nearest frame index."""
        return int(round(timestamp_sec * self.fps))

    @property
    def is_open(self) -> bool:
        return self._backend != "none"

    def __del__(self):
        self.close()
