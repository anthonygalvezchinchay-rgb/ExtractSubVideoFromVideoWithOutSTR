# config.py — SubtitleForge Configuration
"""
Configuración global y defaults para el pipeline de extracción de subtítulos.
Cada parámetro tiene un valor por defecto razonable y puede ser sobreescrito
por el usuario desde el panel de configuración del frontend.
"""

import os

# ─── Quality Presets ───────────────────────────────────────────────────────────
# Presets predefinidos que ajustan múltiples parámetros según la calidad del video.
QUALITY_PRESETS = {
    "eco": {
        "label": "Modo Ahorro (Eco)",
        "fps_extraction": 1,
        "preprocessing_enabled": False,
        "preprocessing_upscale": False,
        "preprocessing_denoise": False,
        "preprocessing_sharpen": False,
        "preprocessing_contrast": False,
        "preprocessing_binarize": False,
        "ssim_threshold": 0.90,
        "confidence_threshold": 0.6,
        "description": "Mínimo consumo de CPU/RAM. Solo 1 FPS, sin filtros de imagen."
    },
    "ultra_low": {
        "label": "Ultra Baja (≤360p)",
        "fps_extraction": 1,
        "preprocessing_enabled": True,
        "preprocessing_upscale": True,
        "preprocessing_denoise": True,
        "preprocessing_sharpen": True,
        "preprocessing_contrast": True,
        "preprocessing_binarize": False,
        "ssim_threshold": 0.88,
        "confidence_threshold": 0.5,
        "description": "Video muy baja calidad. Preprocesamiento agresivo activado."
    },
    "low": {
        "label": "Baja (≤480p)",
        "fps_extraction": 2,
        "preprocessing_enabled": True,
        "preprocessing_upscale": True,
        "preprocessing_denoise": True,
        "preprocessing_sharpen": True,
        "preprocessing_contrast": True,
        "preprocessing_binarize": False,
        "ssim_threshold": 0.90,
        "confidence_threshold": 0.6,
        "description": "Video baja calidad. Preprocesamiento activado para mejorar OCR."
    },
    "medium": {
        "label": "Media (≤720p)",
        "fps_extraction": 2,
        "preprocessing_enabled": False,
        "preprocessing_upscale": False,
        "preprocessing_denoise": False,
        "preprocessing_sharpen": False,
        "preprocessing_contrast": False,
        "preprocessing_binarize": False,
        "ssim_threshold": 0.92,
        "confidence_threshold": 0.7,
        "description": "Video calidad estándar. Configuración balanceada."
    },
    "high": {
        "label": "Alta (≤1080p)",
        "fps_extraction": 3,
        "preprocessing_enabled": False,
        "preprocessing_upscale": False,
        "preprocessing_denoise": False,
        "preprocessing_sharpen": False,
        "preprocessing_contrast": False,
        "preprocessing_binarize": False,
        "ssim_threshold": 0.93,
        "confidence_threshold": 0.75,
        "description": "Video alta calidad. Mayor precisión."
    },
    "ultra": {
        "label": "Ultra (≤4K)",
        "fps_extraction": 2,
        "preprocessing_enabled": False,
        "preprocessing_upscale": False,
        "preprocessing_denoise": False,
        "preprocessing_sharpen": False,
        "preprocessing_contrast": False,
        "preprocessing_binarize": False,
        "ssim_threshold": 0.94,
        "confidence_threshold": 0.8,
        "description": "Video ultra calidad. FPS reducido por peso de frames."
    },
}

# ─── Default Configuration ────────────────────────────────────────────────────
DEFAULT_CONFIG = {
    # Frame extraction
    "fps_extraction": 2,

    # Subtitle zone detection
    "subtitle_zone_mode": "auto",  # "auto" | "top" | "bottom" | "custom"
    "custom_zone": None,            # (x1, y1, x2, y2) if mode="custom"
    "detection_threshold": 0.15,

    # Change detection
    "ssim_threshold": 0.92,
    "min_subtitle_duration": 0.5,

    # Preprocessing
    "preprocessing_enabled": False,
    "preprocessing_upscale": False,
    "preprocessing_denoise": False,
    "preprocessing_sharpen": False,
    "preprocessing_contrast": False,
    "preprocessing_binarize": False,

    # OCR
    "ocr_engine": "auto",           # "auto" | "paddleocr" | "easyocr"
    "paddle_lang": "en",
    "confidence_threshold": 0.7,

    # Language
    "force_language": None,          # None = autodetect

    # Translation
    "translate_enabled": False,
    "translate_to": "es",
    "libretranslate_url": "http://localhost:5000",

    # Output formats
    "output_formats": ["srt"],

    # Max resolution for OCR processing (downscale if larger)
    "max_ocr_resolution": 540,
}

# ─── Server Configuration ─────────────────────────────────────────────────────
SERVER_CONFIG = {
    "host": "0.0.0.0",
    "port": int(os.getenv("PORT", 8000)),
    "upload_dir": os.path.join(os.path.dirname(__file__), "uploads"),
    "output_dir": os.path.join(os.path.dirname(__file__), "output"),
    "temp_dir": os.path.join(os.path.dirname(__file__), "temp"),
    "allowed_extensions": {".mp4", ".avi", ".mkv", ".mov", ".webm", ".m4v", ".flv", ".wmv"},
    "job_expiry_hours": 24,
}

# ─── Supported Languages ──────────────────────────────────────────────────────
SUPPORTED_LANGUAGES = {
    "auto": "Auto-detectar",
    "en": "English",
    "es": "Español",
    "pt": "Português",
    "fr": "Français",
    "de": "Deutsch",
    "it": "Italiano",
    "ja": "日本語",
    "ko": "한국어",
    "zh": "中文",
    "ar": "العربية",
    "ru": "Русский",
    "hi": "हिन्दी",
}

# Map language codes to PaddleOCR language codes
LANG_TO_PADDLE = {
    "en": "en", "es": "es", "pt": "pt", "fr": "fr",
    "de": "de", "it": "it", "ja": "japan", "ko": "korean",
    "zh": "ch", "ar": "ar", "ru": "ru", "hi": "hi",
}

# Map language codes to EasyOCR language codes
LANG_TO_EASYOCR = {
    "en": "en", "es": "es", "pt": "pt", "fr": "fr",
    "de": "de", "it": "it", "ja": "ja", "ko": "ko",
    "zh": "ch_sim", "ar": "ar", "ru": "ru", "hi": "hi",
}
