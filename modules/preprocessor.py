# modules/preprocessor.py
"""
Pipeline de preprocesamiento de imagen para mejorar OCR en videos de baja calidad.
Cada paso es configurable individualmente. Se aplica solo al crop de la zona de subtítulos.

Individual filter functions are also exported so the interactive on-demand
OCR workflow can compose a custom filter chain on a single crop.
"""

import cv2
import numpy as np


# ── Standalone Filter Functions ────────────────────────────────────────────

def upscale_image(image: np.ndarray, factor: float = 2.0) -> np.ndarray:
    """Upscale an image by *factor* using cubic interpolation."""
    if factor <= 1.0:
        return image
    h, w = image.shape[:2]
    return cv2.resize(image, (int(w * factor), int(h * factor)), interpolation=cv2.INTER_CUBIC)


def denoise_image(image: np.ndarray, h: int = 10) -> np.ndarray:
    """Remove compression noise with Non-Local Means Denoising (colour variant)."""
    return cv2.fastNlMeansDenoisingColored(
        image, None,
        h=h,
        hColor=h,
        templateWindowSize=7,
        searchWindowSize=21,
    )


def enhance_contrast(image: np.ndarray, clip_limit: float = 3.0) -> np.ndarray:
    """Apply CLAHE contrast enhancement on the L channel (LAB colour space)."""
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
    l_enhanced = clahe.apply(l_channel)
    lab_enhanced = cv2.merge([l_enhanced, a_channel, b_channel])
    return cv2.cvtColor(lab_enhanced, cv2.COLOR_LAB2BGR)


def sharpen_image(image: np.ndarray) -> np.ndarray:
    """Sharpen text edges with a 3×3 unsharp kernel."""
    kernel = np.array([
        [0, -1, 0],
        [-1, 5, -1],
        [0, -1, 0],
    ], dtype=np.float32)
    return cv2.filter2D(image, -1, kernel)


def binarize_image(image: np.ndarray, block_size: int = 11, c: int = 2) -> np.ndarray:
    """Adaptive Gaussian binarisation (returns a BGR image for API consistency)."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    binary = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=block_size,
        C=c,
    )
    return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)


def pad_image(image: np.ndarray, px: int = 10, colour: tuple = (255, 255, 255)) -> np.ndarray:
    """
    Add a uniform border around the image.

    Padding helps OCR engines avoid clipping text that touches the crop edges,
    a common issue with anime-style outlined subtitles.
    """
    return cv2.copyMakeBorder(
        image, px, px, px, px,
        cv2.BORDER_CONSTANT, value=colour,
    )


# ── Composite Pipeline ────────────────────────────────────────────────────

def preprocess_subtitle_crop(
    crop: np.ndarray,
    upscale: bool = True,
    denoise: bool = True,
    sharpen: bool = True,
    contrast: bool = True,
    binarize: bool = False,
    padding: bool = False,
    upscale_factor: float = 2.0,
) -> np.ndarray:
    """
    Aplica pipeline de preprocesamiento al crop de subtítulo.

    Args:
        crop: Imagen recortada de la zona de subtítulos (BGR)
        upscale: Agrandar la imagen para mejorar reconocimiento
        denoise: Eliminar ruido de compresión
        sharpen: Mejorar bordes del texto
        contrast: Mejorar contraste texto vs fondo (CLAHE)
        binarize: Binarización adaptativa (para textos muy claros/oscuros)
        padding: Add white padding around the crop
        upscale_factor: Factor de escala para upscale

    Returns:
        Imagen preprocesada (BGR)
    """
    result = crop.copy()

    if upscale:
        result = upscale_image(result, upscale_factor)
    if denoise:
        result = denoise_image(result)
    if contrast:
        result = enhance_contrast(result)
    if sharpen:
        result = sharpen_image(result)
    if binarize:
        result = binarize_image(result)
    if padding:
        result = pad_image(result)

    return result

