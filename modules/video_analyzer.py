# modules/video_analyzer.py
"""
Módulo de análisis automático de calidad de video.
Usa ffprobe para extraer metadatos del container y cv2 para verificar.
Genera un quality score y sugiere el preset de configuración óptimo.
"""

import subprocess
import json
import os
from dataclasses import dataclass, field
from typing import Optional
import cv2
import numpy as np


@dataclass
class VideoInfo:
    """Información completa del video analizado."""
    filepath: str
    filename: str
    file_size_bytes: int
    file_size_human: str

    # Video stream
    width: int = 0
    height: int = 0
    fps: float = 0.0
    duration_sec: float = 0.0
    duration_human: str = ""
    codec: str = ""
    bitrate_kbps: int = 0
    total_frames: int = 0
    pixel_format: str = ""

    # Audio stream
    audio_codec: str = ""
    audio_channels: int = 0
    audio_sample_rate: int = 0

    # Quality assessment
    quality_score: int = 0           # 0-100
    quality_category: str = "medium" # ultra_low, low, medium, high, ultra
    quality_label: str = ""
    suggested_preset: str = "medium"

    # Thumbnail
    thumbnail_path: Optional[str] = None

    # Raw ffprobe data
    raw_metadata: dict = field(default_factory=dict)


def _format_file_size(size_bytes: int) -> str:
    """Convierte bytes a formato legible (KB, MB, GB)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    else:
        return f"{size_bytes / (1024 ** 3):.2f} GB"


def _format_duration(seconds: float) -> str:
    """Convierte segundos a formato HH:MM:SS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _run_ffprobe(video_path: str) -> dict:
    """Ejecuta ffprobe y retorna la información en JSON."""
    cmd = [
        'ffprobe', '-v', 'quiet',
        '-print_format', 'json',
        '-show_format', '-show_streams',
        video_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return {}
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return {}


def _calculate_quality_score(width: int, height: int, bitrate_kbps: int, fps: float) -> int:
    """
    Calcula un score de calidad de 0-100 basado en múltiples factores.
    - Resolución contribuye 50% del score
    - Bitrate contribuye 30%
    - FPS contribuye 20%
    """
    # Resolution score (0-50)
    pixels = width * height
    if pixels >= 3840 * 2160:
        res_score = 50
    elif pixels >= 1920 * 1080:
        res_score = 40
    elif pixels >= 1280 * 720:
        res_score = 30
    elif pixels >= 854 * 480:
        res_score = 20
    elif pixels >= 640 * 360:
        res_score = 10
    else:
        res_score = 5

    # Bitrate score (0-30)
    if bitrate_kbps >= 8000:
        br_score = 30
    elif bitrate_kbps >= 4000:
        br_score = 24
    elif bitrate_kbps >= 2000:
        br_score = 18
    elif bitrate_kbps >= 1000:
        br_score = 12
    elif bitrate_kbps >= 500:
        br_score = 6
    else:
        br_score = 3

    # FPS score (0-20)
    if fps >= 60:
        fps_score = 20
    elif fps >= 30:
        fps_score = 16
    elif fps >= 24:
        fps_score = 12
    elif fps >= 15:
        fps_score = 8
    else:
        fps_score = 4

    return min(100, res_score + br_score + fps_score)


def _determine_quality_category(width: int, height: int) -> tuple[str, str]:
    """Determina la categoría de calidad basándose en la resolución."""
    min_dim = min(width, height)
    if min_dim <= 360:
        return "ultra_low", "Ultra Baja (≤360p)"
    elif min_dim <= 480:
        return "low", "Baja (≤480p)"
    elif min_dim <= 720:
        return "medium", "Media (≤720p)"
    elif min_dim <= 1080:
        return "high", "Alta (≤1080p)"
    else:
        return "ultra", "Ultra (≤4K+)"


def generate_thumbnail(video_path: str, output_path: str, timestamp_sec: float = 1.0) -> bool:
    """Genera un thumbnail del video en el timestamp indicado."""
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return False

        cap.set(cv2.CAP_PROP_POS_MSEC, timestamp_sec * 1000)
        ret, frame = cap.read()
        cap.release()

        if not ret or frame is None:
            return False

        # Resize to max 640px width maintaining aspect ratio
        h, w = frame.shape[:2]
        if w > 640:
            scale = 640 / w
            frame = cv2.resize(frame, (640, int(h * scale)))

        cv2.imwrite(output_path, frame)
        return True
    except Exception:
        return False


def analyze_video(video_path: str, output_dir: str = None) -> VideoInfo:
    """
    Analiza un video y retorna información completa incluyendo calidad,
    metadatos técnicos y preset sugerido.
    """
    file_size = os.path.getsize(video_path)

    info = VideoInfo(
        filepath=video_path,
        filename=os.path.basename(video_path),
        file_size_bytes=file_size,
        file_size_human=_format_file_size(file_size),
    )

    # 1. FFprobe analysis
    probe_data = _run_ffprobe(video_path)
    info.raw_metadata = probe_data

    if probe_data:
        # Extract format info
        fmt = probe_data.get("format", {})
        info.duration_sec = float(fmt.get("duration", 0))
        info.duration_human = _format_duration(info.duration_sec)

        overall_bitrate = int(fmt.get("bit_rate", 0)) // 1000
        if overall_bitrate > 0:
            info.bitrate_kbps = overall_bitrate

        # Extract video stream info
        for stream in probe_data.get("streams", []):
            if stream.get("codec_type") == "video":
                info.width = int(stream.get("width", 0))
                info.height = int(stream.get("height", 0))
                info.codec = stream.get("codec_name", "unknown")
                info.pixel_format = stream.get("pix_fmt", "")

                # Parse FPS from r_frame_rate (e.g., "30000/1001")
                r_fps = stream.get("r_frame_rate", "0/1")
                try:
                    num, den = r_fps.split("/")
                    info.fps = float(num) / float(den) if float(den) != 0 else 0
                except (ValueError, ZeroDivisionError):
                    info.fps = 0

                # Stream bitrate
                stream_br = int(stream.get("bit_rate", 0)) // 1000
                if stream_br > 0:
                    info.bitrate_kbps = stream_br

                # Total frames
                nb_frames = stream.get("nb_frames", "0")
                try:
                    info.total_frames = int(nb_frames)
                except ValueError:
                    if info.fps > 0 and info.duration_sec > 0:
                        info.total_frames = int(info.fps * info.duration_sec)

            elif stream.get("codec_type") == "audio":
                info.audio_codec = stream.get("codec_name", "")
                info.audio_channels = int(stream.get("channels", 0))
                info.audio_sample_rate = int(stream.get("sample_rate", 0))

    # 2. Fallback: OpenCV verification
    if info.width == 0 or info.height == 0:
        cap = cv2.VideoCapture(video_path)
        if cap.isOpened():
            info.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            info.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            info.fps = cap.get(cv2.CAP_PROP_FPS) or info.fps
            info.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if info.total_frames > 0 and info.fps > 0:
                info.duration_sec = info.total_frames / info.fps
                info.duration_human = _format_duration(info.duration_sec)
            cap.release()

    # 3. Calculate quality
    info.quality_score = _calculate_quality_score(
        info.width, info.height, info.bitrate_kbps, info.fps
    )
    info.quality_category, info.quality_label = _determine_quality_category(
        info.width, info.height
    )
    info.suggested_preset = info.quality_category

    # 4. Generate thumbnail
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        thumb_path = os.path.join(output_dir, "thumbnail.jpg")
        if generate_thumbnail(video_path, thumb_path):
            info.thumbnail_path = thumb_path

    return info


def video_info_to_dict(info: VideoInfo) -> dict:
    """Convierte VideoInfo a diccionario para JSON serialization."""
    return {
        "filename": info.filename,
        "file_size_bytes": info.file_size_bytes,
        "file_size_human": info.file_size_human,
        "width": info.width,
        "height": info.height,
        "resolution": f"{info.width}x{info.height}",
        "fps": round(info.fps, 2),
        "duration_sec": round(info.duration_sec, 2),
        "duration_human": info.duration_human,
        "codec": info.codec,
        "bitrate_kbps": info.bitrate_kbps,
        "total_frames": info.total_frames,
        "pixel_format": info.pixel_format,
        "audio_codec": info.audio_codec,
        "audio_channels": info.audio_channels,
        "quality_score": info.quality_score,
        "quality_category": info.quality_category,
        "quality_label": info.quality_label,
        "suggested_preset": info.suggested_preset,
    }
