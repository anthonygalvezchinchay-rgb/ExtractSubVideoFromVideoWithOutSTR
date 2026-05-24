# modules/subtitle_detector.py
"""
Detección automática de la posición de subtítulos en el video.
Analiza la varianza de píxeles entre frames para determinar
si los subtítulos aparecen en la parte superior o inferior.
"""

import cv2
import numpy as np
from dataclasses import dataclass
from typing import Optional


@dataclass
class SubtitleZone:
    """Zona detectada donde aparecen los subtítulos."""
    position: str        # "top" | "bottom" | "custom" | "both"
    y_start: int
    y_end: int
    x_start: int
    x_end: int
    confidence: float
    preview_image: Optional[np.ndarray] = None


def detect_subtitle_zone(
    frames: list[np.ndarray],
    mode: str = "auto",
    custom_zone: Optional[tuple] = None,
) -> SubtitleZone:
    """
    Analiza múltiples frames para detectar automáticamente
    dónde aparecen los subtítulos (franja superior o inferior).

    Args:
        frames: Lista de frames del video
        mode: "auto", "top", "bottom", "custom"
        custom_zone: Tupla (x1, y1, x2, y2) para modo custom

    Returns:
        SubtitleZone con la posición detectada
    """
    if not frames:
        raise ValueError("No hay frames para analizar")

    height, width = frames[0].shape[:2]

    if mode == "custom" and custom_zone:
        x1, y1, x2, y2 = custom_zone
        return SubtitleZone("custom", y1, y2, x1, x2, 1.0)

    if mode == "bottom":
        zone = SubtitleZone("bottom", int(height * 0.75), height, 0, width, 1.0)
        zone.preview_image = _generate_zone_preview(frames[0], zone)
        return zone

    if mode == "top":
        zone = SubtitleZone("top", 0, int(height * 0.25), 0, width, 1.0)
        zone.preview_image = _generate_zone_preview(frames[0], zone)
        return zone

    # ─── AUTO mode ─────────────────────────────────────────────────────────
    # Analyze pixel variance between frames to find where text changes happen
    top_scores = []
    bottom_scores = []
    sample_count = min(len(frames), 60)

    for i in range(1, sample_count):
        diff = cv2.absdiff(frames[i], frames[i - 1])
        gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)

        top_region = gray[:int(height * 0.25), :]
        bottom_region = gray[int(height * 0.75):, :]

        top_scores.append(np.mean(top_region))
        bottom_scores.append(np.mean(bottom_region))

    avg_top = np.mean(top_scores) if top_scores else 0
    avg_bottom = np.mean(bottom_scores) if bottom_scores else 0

    # Check if BOTH zones have significant activity (dual subtitles)
    threshold = 1.5  # Minimum activity to consider
    has_top = avg_top > threshold
    has_bottom = avg_bottom > threshold

    if has_top and has_bottom and abs(avg_top - avg_bottom) < 2.0:
        # Both zones active - likely dual subtitles
        zone = SubtitleZone(
            position="both",
            y_start=int(height * 0.72),
            y_end=height,
            x_start=int(width * 0.05),
            x_end=int(width * 0.95),
            confidence=min(avg_top, avg_bottom) / (max(avg_top, avg_bottom) + 1e-5)
        )
    elif avg_bottom >= avg_top:
        zone = SubtitleZone(
            position="bottom",
            y_start=int(height * 0.72),
            y_end=height,
            x_start=int(width * 0.05),
            x_end=int(width * 0.95),
            confidence=avg_bottom / (avg_top + 1e-5)
        )
    else:
        zone = SubtitleZone(
            position="top",
            y_start=0,
            y_end=int(height * 0.28),
            x_start=int(width * 0.05),
            x_end=int(width * 0.95),
            confidence=avg_top / (avg_bottom + 1e-5)
        )

    zone.preview_image = _generate_zone_preview(frames[0], zone)
    return zone


def crop_subtitle_region(frame: np.ndarray, zone: SubtitleZone) -> np.ndarray:
    """Recorta el frame a la zona de subtítulo detectada."""
    return frame[zone.y_start:zone.y_end, zone.x_start:zone.x_end]


def _generate_zone_preview(frame: np.ndarray, zone: SubtitleZone) -> np.ndarray:
    """Genera una imagen de preview con la zona resaltada."""
    preview = frame.copy()
    # Draw green rectangle around detected zone
    cv2.rectangle(
        preview,
        (zone.x_start, zone.y_start),
        (zone.x_end, zone.y_end),
        (0, 255, 0), 3
    )
    # Add label
    label = f"Subtitles: {zone.position.upper()} ({zone.confidence:.1f})"
    cv2.putText(
        preview, label,
        (zone.x_start + 10, zone.y_start - 10),
        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2
    )
    return preview
