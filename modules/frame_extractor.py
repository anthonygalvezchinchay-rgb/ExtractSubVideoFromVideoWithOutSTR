# modules/frame_extractor.py
"""
Extracción de frames del video usando OpenCV.
Soporta extracción a FPS configurable, downscale automático para videos >1080p,
y modo streaming (generador) para no cargar todos los frames en RAM.
"""

import cv2
import numpy as np
from typing import Callable, Optional


def extract_frames(
    video_path: str,
    fps_target: float = 2.0,
    max_resolution: int = 1080,
    on_progress: Optional[Callable] = None,
) -> tuple[list[np.ndarray], list[float]]:
    """
    Extrae frames del video al FPS objetivo.

    Args:
        video_path: Ruta al archivo de video
        fps_target: Frames por segundo a extraer
        max_resolution: Resolución máxima (downscale si es mayor)
        on_progress: Callback (percent, message) para reportar progreso

    Returns:
        Tuple de (lista de frames como numpy arrays, lista de timestamps en segundos)
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"No se pudo abrir el video: {video_path}")

    video_fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if video_fps <= 0:
        video_fps = 30.0  # fallback

    # Calculate frame interval
    frame_interval = max(1, int(video_fps / fps_target))

    # Calculate scale factor for downscale
    scale = 1.0
    min_dim = min(width, height)
    if min_dim > max_resolution:
        scale = max_resolution / min_dim

    frames = []
    timestamps = []
    frame_idx = 0
    extracted = 0

    # Estimate total frames to extract for progress
    estimated_total = total_frames // frame_interval if total_frames > 0 else 1

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % frame_interval == 0:
            # Downscale if needed
            if scale < 1.0:
                new_w = int(width * scale)
                new_h = int(height * scale)
                frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)

            timestamp = frame_idx / video_fps
            frames.append(frame)
            timestamps.append(timestamp)
            extracted += 1

            # Report progress
            if on_progress and estimated_total > 0:
                percent = min(100, int((extracted / estimated_total) * 100))
                if extracted % 20 == 0 or percent >= 100:
                    on_progress(percent, f"Frame {extracted}/{estimated_total} extraído ({timestamp:.1f}s)")

        frame_idx += 1

    cap.release()

    if not frames:
        raise RuntimeError("No se pudieron extraer frames del video")

    return frames, timestamps


def extract_frames_streaming(
    video_path: str,
    fps_target: float = 2.0,
    max_resolution: int = 1080,
):
    """
    Generador que extrae frames uno a uno para procesar en streaming
    sin cargar todos en memoria. Útil para videos muy largos.

    Yields:
        Tuple de (frame numpy array, timestamp en segundos, frame_index, total_estimated)
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"No se pudo abrir el video: {video_path}")

    video_fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if video_fps <= 0:
        video_fps = 30.0

    frame_interval = max(1, int(video_fps / fps_target))
    estimated_total = total_frames // frame_interval if total_frames > 0 else 1

    scale = 1.0
    min_dim = min(width, height)
    if min_dim > max_resolution:
        scale = max_resolution / min_dim

    frame_idx = 0
    extracted = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % frame_interval == 0:
            if scale < 1.0:
                new_w = int(width * scale)
                new_h = int(height * scale)
                frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)

            timestamp = frame_idx / video_fps
            yield frame, timestamp, extracted, estimated_total
            extracted += 1

        frame_idx += 1

    cap.release()
