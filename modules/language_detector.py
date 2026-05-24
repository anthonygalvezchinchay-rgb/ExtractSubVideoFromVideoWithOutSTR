# modules/language_detector.py
"""
Detección automática de idioma del texto extraído por OCR.
Usa lingua-py para máxima precisión en textos cortos.
"""

from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Language detector singleton (lazy init)
_DETECTOR = None


def _get_detector():
    """Inicializa el detector de idioma (singleton)."""
    global _DETECTOR
    if _DETECTOR is None:
        try:
            from lingua import Language, LanguageDetectorBuilder
            _DETECTOR = LanguageDetectorBuilder.from_languages(
                Language.ENGLISH,
                Language.SPANISH,
                Language.PORTUGUESE,
                Language.FRENCH,
                Language.GERMAN,
                Language.ITALIAN,
                Language.JAPANESE,
                Language.KOREAN,
                Language.CHINESE,
                Language.ARABIC,
                Language.RUSSIAN,
                Language.HINDI,
            ).build()
        except ImportError:
            logger.warning("lingua-language-detector no instalado. Usando fallback a 'en'.")
            _DETECTOR = None
    return _DETECTOR


# Mapping from lingua language names to our standard codes
_LANG_NAME_TO_CODE = {
    "ENGLISH": "en",
    "SPANISH": "es",
    "PORTUGUESE": "pt",
    "FRENCH": "fr",
    "GERMAN": "de",
    "ITALIAN": "it",
    "JAPANESE": "ja",
    "KOREAN": "ko",
    "CHINESE": "zh",
    "ARABIC": "ar",
    "RUSSIAN": "ru",
    "HINDI": "hi",
}


def detect_language(texts: list[str], force_language: Optional[str] = None) -> dict:
    """
    Detecta el idioma predominante de una lista de textos OCR.

    Args:
        texts: Lista de textos extraídos por OCR
        force_language: Si se especifica, retorna este idioma sin detectar

    Returns:
        dict con: language_code, language_name, confidence
    """
    if force_language:
        return {
            "language_code": force_language,
            "language_name": force_language.upper(),
            "confidence": 1.0,
        }

    # Combine texts, filter short ones
    combined = " ".join(t for t in texts if t and len(t) > 3)[:3000]

    if not combined.strip():
        return {"language_code": "en", "language_name": "ENGLISH", "confidence": 0.0}

    detector = _get_detector()
    if detector is None:
        return {"language_code": "en", "language_name": "ENGLISH", "confidence": 0.5}

    try:
        result = detector.detect_language_of(combined)
        if result is None:
            return {"language_code": "en", "language_name": "ENGLISH", "confidence": 0.5}

        lang_name = result.name
        lang_code = _LANG_NAME_TO_CODE.get(lang_name, "en")

        # Get confidence values for more detail
        confidence = 1.0
        try:
            confidence_values = detector.compute_language_confidence_values(combined)
            if confidence_values:
                confidence = confidence_values[0].value
        except Exception:
            pass

        return {
            "language_code": lang_code,
            "language_name": lang_name,
            "confidence": round(confidence, 3),
        }
    except Exception as e:
        logger.warning(f"Error detectando idioma: {e}")
        return {"language_code": "en", "language_name": "ENGLISH", "confidence": 0.0}
