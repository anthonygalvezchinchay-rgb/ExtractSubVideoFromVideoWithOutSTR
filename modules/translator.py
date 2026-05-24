# modules/translator.py
"""
Traducción de subtítulos usando LibreTranslate (self-hosted, gratuito).
Traduce en batches para eficiencia y maneja errores gracefully.
"""

import requests
import logging
import time

logger = logging.getLogger(__name__)

DEFAULT_URL = "http://localhost:5000"


def check_libretranslate(url: str = DEFAULT_URL) -> bool:
    """Verifica si LibreTranslate está disponible."""
    try:
        resp = requests.get(f"{url}/languages", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def get_available_languages(url: str = DEFAULT_URL) -> list[dict]:
    """Obtiene la lista de idiomas soportados por LibreTranslate."""
    try:
        resp = requests.get(f"{url}/languages", timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return []


def translate_text(
    text: str,
    source: str = "auto",
    target: str = "es",
    url: str = DEFAULT_URL,
) -> str:
    """Traduce un texto individual."""
    try:
        payload = {
            "q": text,
            "source": source,
            "target": target,
            "format": "text",
        }
        resp = requests.post(f"{url}/translate", json=payload, timeout=30)
        if resp.status_code == 200:
            return resp.json().get("translatedText", text)
        logger.warning(f"LibreTranslate error {resp.status_code}: {resp.text}")
        return text
    except Exception as e:
        logger.warning(f"Translation error: {e}")
        return text


def translate_blocks(
    blocks: list[dict],
    source_lang: str = "auto",
    target_lang: str = "es",
    url: str = DEFAULT_URL,
    batch_size: int = 10,
    on_progress=None,
) -> list[dict]:
    """
    Traduce una lista de bloques de subtítulos.
    Cada bloque recibe un campo 'text_translated'.

    Args:
        blocks: Lista de bloques con campo 'text'
        source_lang: Idioma fuente ("auto" para auto-detectar)
        target_lang: Idioma destino
        url: URL de LibreTranslate
        batch_size: Número de subtítulos por batch
        on_progress: Callback (percent, message)

    Returns:
        Lista de bloques con campo 'text_translated' añadido
    """
    if not check_libretranslate(url):
        logger.warning("LibreTranslate no está disponible. Saltando traducción.")
        return blocks

    total = len(blocks)
    translated_blocks = []

    for i in range(0, total, batch_size):
        batch = blocks[i:i + batch_size]

        for block in batch:
            text = block.get("text", "")
            if text.strip():
                translated_text = translate_text(text, source_lang, target_lang, url)
                block["text_translated"] = translated_text
            else:
                block["text_translated"] = ""
            translated_blocks.append(block)

        if on_progress:
            done = min(i + batch_size, total)
            percent = int((done / total) * 100)
            on_progress(percent, f"Traduciendo: {done}/{total} subtítulos")

        # Small delay between batches to not overwhelm the server
        if i + batch_size < total:
            time.sleep(0.2)

    return translated_blocks
