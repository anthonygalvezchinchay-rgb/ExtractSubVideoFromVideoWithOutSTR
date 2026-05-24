# modules/change_detector.py
"""
Detección de cambios de subtítulo usando SSIM (Structural Similarity Index).
Compara frames consecutivos para determinar cuándo cambia el texto del subtítulo.
Agrupa resultados en bloques con timestamps de inicio/fin.
"""

import numpy as np
import cv2
from skimage.metrics import structural_similarity as ssim
from dataclasses import dataclass


@dataclass
class SubtitleChange:
    """Representa un cambio detectado en el subtítulo."""
    frame_index: int
    timestamp_sec: float
    is_new_subtitle: bool
    ssim_score: float
    is_empty: bool = False  # True si el frame no tiene subtítulo visible


def _is_empty_region(crop_gray: np.ndarray, variance_threshold: float = 15.0) -> bool:
    """
    Detecta si una región está vacía (sin texto visible).
    Regiones sin texto tienen varianza de píxeles muy baja.
    """
    return np.std(crop_gray) < variance_threshold


def detect_subtitle_changes(
    subtitle_crops: list[np.ndarray],
    timestamps: list[float],
    ssim_threshold: float = 0.92,
    min_duration: float = 0.5,
    on_progress=None,
) -> list[SubtitleChange]:
    """
    Detecta cuándo cambia el subtítulo comparando SSIM entre frames consecutivos.

    Args:
        subtitle_crops: Lista de imágenes recortadas de la zona de subtítulos
        timestamps: Lista de timestamps en segundos
        ssim_threshold: Umbral de SSIM (< este valor = cambio detectado)
        min_duration: Duración mínima entre cambios (evita falsos positivos)
        on_progress: Callback opcional (percent, message)

    Returns:
        Lista de SubtitleChange indicando cada cambio detectado
    """
    changes = []
    prev_crop = None
    last_change_time = -999
    total = len(subtitle_crops)

    for i, (crop, ts) in enumerate(zip(subtitle_crops, timestamps)):
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        is_empty = _is_empty_region(gray)

        if prev_crop is None:
            changes.append(SubtitleChange(i, ts, True, 0.0, is_empty))
            prev_crop = gray
            last_change_time = ts
            continue

        # Ensure same size for SSIM comparison
        if prev_crop.shape != gray.shape:
            gray = cv2.resize(gray, (prev_crop.shape[1], prev_crop.shape[0]))

        score = ssim(prev_crop, gray, data_range=255)
        is_change = (score < ssim_threshold) and (ts - last_change_time >= min_duration)

        if is_change:
            changes.append(SubtitleChange(i, ts, True, score, is_empty))
            last_change_time = ts
        else:
            changes.append(SubtitleChange(i, ts, False, score, is_empty))

        prev_crop = gray

        if on_progress and total > 0 and i % 50 == 0:
            on_progress(int((i / total) * 100), f"Analizando cambios: frame {i}/{total}")

    return changes


def group_into_blocks(
    ocr_results: list[dict],
    changes: list[SubtitleChange],
) -> list[dict]:
    """
    Agrupa resultados OCR en bloques de subtítulo con tiempos de inicio/fin.

    Returns:
        Lista de bloques: {index, text, start_sec, end_sec, duration_sec, confidence}
    """
    blocks = []
    current_text = ""
    current_start = None
    current_confidence = 0.0
    block_index = 1

    for i, change in enumerate(changes):
        if change.is_new_subtitle:
            # Close previous block
            if current_text.strip() and current_start is not None:
                blocks.append({
                    "index": block_index,
                    "text": current_text.strip(),
                    "start_sec": current_start,
                    "end_sec": change.timestamp_sec,
                    "duration_sec": round(change.timestamp_sec - current_start, 3),
                    "confidence": round(current_confidence, 3),
                })
                block_index += 1

            # Open new block
            current_start = change.timestamp_sec
            if i < len(ocr_results):
                current_text = ocr_results[i].get("text", "")
                current_confidence = ocr_results[i].get("confidence", 0.0)
            else:
                current_text = ""
                current_confidence = 0.0
        else:
            # Update with longer/better text if found
            if i < len(ocr_results):
                new_text = ocr_results[i].get("text", "")
                new_conf = ocr_results[i].get("confidence", 0.0)
                if len(new_text) > len(current_text) or new_conf > current_confidence:
                    current_text = new_text
                    current_confidence = new_conf

    # Close last block
    if current_text.strip() and current_start is not None:
        last_ts = changes[-1].timestamp_sec + 2.0
        blocks.append({
            "index": block_index,
            "text": current_text.strip(),
            "start_sec": current_start,
            "end_sec": last_ts,
            "duration_sec": round(last_ts - current_start, 3),
            "confidence": round(current_confidence, 3),
        })

    return blocks
