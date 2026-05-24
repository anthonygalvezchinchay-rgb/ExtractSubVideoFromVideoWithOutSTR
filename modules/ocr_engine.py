# modules/ocr_engine.py
"""
Motor OCR unificado con soporte para PaddleOCR y EasyOCR.
Detecta automáticamente la mejor opción disponible (GPU ROCm / CPU).
Provee interfaz consistente independientemente del backend.
"""

import numpy as np
from typing import Optional
import logging
import inspect
import os

# --- LIMITAR USO DE HILOS CPU (Evita congelar/crashear PCs de bajos recursos) ---
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"
os.environ["SHAPE_GEN_NUM_THREADS"] = "1"

try:
    import torch
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
except ImportError:
    pass

logger = logging.getLogger(__name__)


class OCREngine:
    """
    Motor OCR unificado que abstrae PaddleOCR y EasyOCR.
    Selecciona automáticamente el mejor backend disponible.
    """

    def __init__(self, engine: str = "auto", lang: str = "en", confidence_threshold: float = 0.7, lazy: bool = False):
        """
        Args:
            engine: "auto", "paddleocr", "easyocr", "tesseract", "manga_ocr"
            lang: Código de idioma
            confidence_threshold: Umbral mínimo de confianza
            lazy: If True, defer backend initialisation until the first recognize() call.
        """
        self.engine_name = engine
        self.lang = lang
        self.confidence_threshold = confidence_threshold
        self._ocr = None
        self._backend = None
        self._lazy = lazy
        self._initialized = False

        if not lazy:
            self._initialize(engine, lang)
            self._initialized = True

    def _ensure_initialized(self):
        """Lazy init guard — called before the first recognize()."""
        if not self._initialized:
            self._initialize(self.engine_name, self.lang)
            self._initialized = True

    def _initialize(self, engine: str, lang: str):
        """Inicializa el motor OCR seleccionado."""
        if engine == "auto":
            # MangaOCR first for Japanese (best precision)
            if lang in ("ja", "jp", "japan") and self._try_manga_ocr():
                return
            # PaddleOCR/EasyOCR for other languages (or fallback for Japanese)
            if lang in ("ja", "jp", "japan"):
                if self._try_paddle(lang):
                    return
                if self._try_easyocr(lang):
                    return
            # Tesseract for Western/Latin languages (very fast/light)
            if lang not in ("ja", "jp", "japan") and self._try_tesseract(lang):
                return
            # Generic fallbacks
            if self._try_paddle(lang):
                return
            if self._try_easyocr(lang):
                return
            if self._try_tesseract(lang):
                return
            raise RuntimeError("No se pudo inicializar ningún motor OCR. Instala pytesseract, paddleocr, easyocr o manga-ocr.")
        elif engine == "tesseract":
            if not self._try_tesseract(lang):
                raise RuntimeError("No se pudo inicializar Tesseract OCR. Asegúrate de tener instalado tesseract-ocr en el sistema y 'pytesseract' en python.")
        elif engine == "manga_ocr":
            if not self._try_manga_ocr():
                raise RuntimeError("No se pudo inicializar MangaOCR. Instala 'manga-ocr' via pip.")
        elif engine == "paddleocr":
            if not self._try_paddle(lang):
                raise RuntimeError("No se pudo inicializar PaddleOCR.")
        elif engine == "easyocr":
            if not self._try_easyocr(lang):
                raise RuntimeError("No se pudo inicializar EasyOCR.")

    def _try_paddle(self, lang: str) -> bool:
        """Intenta inicializar PaddleOCR."""
        try:
            from paddleocr import PaddleOCR
            # Map language code to PaddleOCR format
            paddle_lang_map = {
                "en": "en", "es": "es", "pt": "pt", "fr": "fr",
                "de": "de", "it": "it", "ja": "japan", "ko": "korean",
                "zh": "ch", "ar": "ar", "ru": "ru", "hi": "hi",
            }
            paddle_lang = paddle_lang_map.get(lang, "en")

            # Check for ROCm GPU
            gpu_available = False
            try:
                import paddle
                gpu_available = paddle.is_compiled_with_rocm() or paddle.is_compiled_with_cuda()
            except Exception:
                pass

            signature = inspect.signature(PaddleOCR.__init__)
            if "use_angle_cls" in signature.parameters:
                # PaddleOCR 2.x
                ocr_kwargs = {
                    "use_angle_cls": True,
                    "lang": paddle_lang,
                    "show_log": False,
                    "use_gpu": gpu_available,
                }
            else:
                # PaddleOCR 3.x delegates device selection to PaddleX.
                ocr_kwargs = {
                    "lang": paddle_lang,
                    "use_textline_orientation": True,
                    "device": "gpu" if gpu_available else "cpu",
                    "enable_mkldnn": False,
                }

            self._ocr = PaddleOCR(**ocr_kwargs)
            self._backend = "paddleocr" + (" (GPU)" if gpu_available else " (CPU)")
            logger.info(f"PaddleOCR inicializado: {self._backend}")
            return True
        except ImportError:
            logger.info("PaddleOCR no disponible")
            return False
        except Exception as e:
            logger.warning(f"Error inicializando PaddleOCR: {e}")
            return False

    def _try_easyocr(self, lang: str) -> bool:
        """Intenta inicializar EasyOCR."""
        try:
            import easyocr
            # Map language code to EasyOCR format
            easyocr_lang_map = {
                "en": "en", "es": "es", "pt": "pt", "fr": "fr",
                "de": "de", "it": "it", "ja": "ja", "ko": "ko",
                "zh": "ch_sim", "ar": "ar", "ru": "ru", "hi": "hi",
            }
            easyocr_lang = easyocr_lang_map.get(lang, "en")

            # EasyOCR uses PyTorch - check GPU
            gpu_available = False
            try:
                import torch
                gpu_available = torch.cuda.is_available()
            except Exception:
                pass

            self._ocr = easyocr.Reader(
                [easyocr_lang],
                gpu=gpu_available,
                verbose=False,
            )
            self._backend = "easyocr" + (" (GPU)" if gpu_available else " (CPU)")
            logger.info(f"EasyOCR inicializado: {self._backend}")
            return True
        except ImportError:
            logger.info("EasyOCR no disponible")
            return False
        except Exception as e:
            logger.warning(f"Error inicializando EasyOCR: {e}")
            return False

    def _try_tesseract(self, lang: str) -> bool:
        """Intenta inicializar Tesseract OCR."""
        try:
            import pytesseract
            # Test if tesseract is installed
            pytesseract.get_tesseract_version()
            tess_lang_map = {
                "en": "eng", "es": "spa", "pt": "por", "fr": "fra",
                "de": "deu", "it": "ita", "ja": "jpn", "ko": "kor",
                "zh": "chi_sim", "ar": "ara", "ru": "rus", "hi": "hin",
            }
            self.tess_lang = tess_lang_map.get(lang, "eng")
            self._backend = "tesseract (CPU - Ultra Liviano)"
            logger.info(f"Tesseract OCR inicializado: {self._backend}")
            return True
        except Exception as e:
            logger.info(f"Tesseract OCR no disponible o pytesseract no instalado: {e}")
            return False

    def _try_manga_ocr(self) -> bool:
        """Intenta inicializar MangaOCR (vision-transformer for Japanese/manga text)."""
        try:
            from manga_ocr import MangaOcr
            self._ocr = MangaOcr()
            self._backend = "manga_ocr (CPU)"
            logger.info(f"MangaOCR inicializado: {self._backend}")
            return True
        except ImportError:
            logger.info("MangaOCR no disponible (pip install manga-ocr)")
            return False
        except Exception as e:
            logger.warning(f"Error inicializando MangaOCR: {e}")
            return False

    @property
    def backend_name(self) -> str:
        """Retorna el nombre del backend activo."""
        self._ensure_initialized()
        return self._backend or "none"

    def recognize(self, image: np.ndarray) -> dict:
        """
        Ejecuta OCR sobre una imagen.

        Args:
            image: Imagen BGR (numpy array)

        Returns:
            dict con: text, confidence, lines (lista de líneas individuales)
        """
        self._ensure_initialized()

        if self._backend and self._backend.startswith("paddleocr"):
            return self._recognize_paddle(image)
        elif self._backend and self._backend.startswith("easyocr"):
            return self._recognize_easyocr(image)
        elif self._backend and self._backend.startswith("tesseract"):
            return self._recognize_tesseract(image)
        elif self._backend and self._backend.startswith("manga_ocr"):
            return self._recognize_manga_ocr(image)
        return {"text": "", "confidence": 0.0, "lines": []}

    def _recognize_paddle(self, image: np.ndarray) -> dict:
        """OCR con PaddleOCR."""
        try:
            ocr_signature = inspect.signature(self._ocr.ocr)
            if "cls" in ocr_signature.parameters:
                result = self._ocr.ocr(image, cls=True)
            else:
                result = self._ocr.ocr(image)

            lines = []
            if result and isinstance(result[0], dict):
                for text, confidence in zip(
                    result[0].get("rec_texts", []),
                    result[0].get("rec_scores", []),
                ):
                    if confidence >= self.confidence_threshold:
                        lines.append({
                            "text": text,
                            "confidence": round(float(confidence), 3),
                        })
            elif result and result[0]:
                for line in result[0]:
                    text = line[1][0]
                    confidence = line[1][1]
                    if confidence >= self.confidence_threshold:
                        lines.append({
                            "text": text,
                            "confidence": round(confidence, 3),
                        })

            full_text = " ".join(l["text"] for l in lines)
            avg_conf = sum(l["confidence"] for l in lines) / len(lines) if lines else 0.0

            return {
                "text": _post_process_text(full_text),
                "confidence": round(avg_conf, 3),
                "lines": lines,
            }
        except Exception as e:
            logger.warning(f"PaddleOCR error: {e}")
            return {"text": "", "confidence": 0.0, "lines": []}

    def _recognize_easyocr(self, image: np.ndarray) -> dict:
        """OCR con EasyOCR."""
        try:
            results = self._ocr.readtext(image)
            lines = []
            for (bbox, text, confidence) in results:
                if confidence >= self.confidence_threshold:
                    lines.append({
                        "text": text,
                        "confidence": round(confidence, 3),
                    })

            full_text = " ".join(l["text"] for l in lines)
            avg_conf = sum(l["confidence"] for l in lines) / len(lines) if lines else 0.0

            return {
                "text": _post_process_text(full_text),
                "confidence": round(avg_conf, 3),
                "lines": lines,
            }
        except Exception as e:
            logger.warning(f"EasyOCR error: {e}")
            return {"text": "", "confidence": 0.0, "lines": []}

    def _recognize_tesseract(self, image: np.ndarray) -> dict:
        """OCR con Tesseract."""
        try:
            import pytesseract
            import cv2
            # Tesseract works best on grayscale images
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            # Threshold to make it binary (black and white text)
            _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            text = pytesseract.image_to_string(thresh, lang=self.tess_lang).strip()
            
            lines = []
            if text:
                for line in text.split("\n"):
                    if line.strip():
                        lines.append({
                            "text": line.strip(),
                            "confidence": 0.85,
                        })

            confidence = 0.85 if text else 0.0

            return {
                "text": _post_process_text(text),
                "confidence": confidence,
                "lines": lines,
            }
        except Exception as e:
            logger.warning(f"Tesseract OCR error: {e}")
            return {"text": "", "confidence": 0.0, "lines": []}

    def _recognize_manga_ocr(self, image: np.ndarray) -> dict:
        """OCR con MangaOCR (vision transformer optimised for Japanese manga/anime)."""
        try:
            import cv2
            from PIL import Image as PILImage
            # MangaOCR expects an RGB PIL Image
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            pil_img = PILImage.fromarray(rgb)
            text = self._ocr(pil_img)
            lines = []
            if text and text.strip():
                for line in text.strip().split("\n"):
                    if line.strip():
                        lines.append({"text": line.strip(), "confidence": 0.90})
            confidence = 0.90 if text else 0.0
            return {
                "text": _post_process_text(text),
                "confidence": confidence,
                "lines": lines,
            }
        except Exception as e:
            logger.warning(f"MangaOCR error: {e}")
            return {"text": "", "confidence": 0.0, "lines": []}

    def change_language(self, lang: str):
        """Reinicializa el motor con un idioma diferente."""
        self.lang = lang
        self._initialized = False
        self._initialize(self.engine_name, lang)
        self._initialized = True


def _post_process_text(text: str) -> str:
    """
    Post-procesamiento del texto OCR:
    - Normaliza espacios
    - Elimina caracteres basura comunes
    - Limpia inicio/fin
    """
    if not text:
        return ""

    # Normalize whitespace
    text = " ".join(text.split())

    # Remove common OCR artifacts
    text = text.replace("|", "I")
    text = text.replace("}", ")")
    text = text.replace("{", "(")

    return text.strip()
