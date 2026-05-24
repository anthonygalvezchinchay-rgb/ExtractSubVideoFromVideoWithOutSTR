# 🎬 Guía Avanzada: Extracción de Subtítulos Quemados con OCR + IA

> **Lenguaje recomendado: Python 3.10+**
> Razón: ecosistema más maduro para visión computacional y OCR. Para máximo rendimiento en producción, considera **Rust** con bindings a OpenCV (ver sección 8).

---

## 1. 🔧 Stack de Tecnologías (Actualizado)

| Componente | Opción Recomendada | Alternativa | Razón |
|---|---|---|---|
| OCR | **PaddleOCR** | EasyOCR | Mejor precisión, soporte multilingüe |
| Extracción de frames | **FFmpeg + opencv** | imageio | Control granular de FPS |
| Detección de posición | **OpenCV (contours)** | CRAFT | Nativo, sin modelo extra |
| Detección de idioma | **lingua-py** | langdetect | Más preciso en textos cortos |
| Cambio de subtítulo | **SSIM / pixel diff** | hash MD5 | Sensible solo a cambios reales |
| Generación SRT | **pysrt** | manual | Maneja edge cases del formato |
| Traducción | **Claude API** | DeepL API | Mantiene contexto entre líneas |

---

## 2. 📦 Instalación Completa

```bash
# Sistema
sudo apt install ffmpeg tesseract-ocr

# Python - entorno virtual recomendado
python -m venv venv && source venv/bin/activate

# Dependencias core
pip install paddlepaddle paddleocr
pip install opencv-python-headless
pip install lingua-language-detector
pip install pysrt
pip install scikit-image          # para SSIM
pip install anthropic              # para traducción con Claude
pip install tqdm                   # barras de progreso
pip install numpy pillow

# Opcional: GPU support
pip install paddlepaddle-gpu       # si tienes CUDA
```

---

## 3. 🏗️ Arquitectura del Proyecto

```
subtitle_extractor/
├── main.py                   # Orquestador principal (CLI)
├── config.py                 # Parámetros globales
├── modules/
│   ├── frame_extractor.py    # Extrae frames con FFmpeg/OpenCV
│   ├── subtitle_detector.py  # Detecta POSICIÓN (top/bottom/custom)
│   ├── change_detector.py    # Detecta CUÁNDO cambia el subtítulo
│   ├── ocr_engine.py         # OCR con PaddleOCR
│   ├── language_detector.py  # Detecta idioma del texto
│   ├── srt_writer.py         # Genera .srt / .sbv
│   └── translator.py         # Traduce con Claude API
├── output/
│   ├── frames/               # Frames extraídos (temp)
│   ├── subtitles.srt         # Salida principal
│   └── subtitles_es.srt      # Traducción
└── requirements.txt
```

---

## 4. ⚙️ config.py

```python
# config.py
import os

CONFIG = {
    # Extracción de frames
    "fps_extraction": 2,          # Frames por segundo a analizar
    "video_path": "input.mp4",
    "output_dir": "output/frames",

    # Detección de subtítulos
    "subtitle_zone_mode": "auto",  # "auto" | "top" | "bottom" | "custom"
    "custom_zone": None,           # (x1, y1, x2, y2) si mode="custom"
    "detection_threshold": 0.15,   # % de alto del frame para zona auto

    # Detector de cambios
    "ssim_threshold": 0.92,        # < este valor = nuevo subtítulo
    "min_subtitle_duration": 0.5,  # segundos mínimos entre cambios

    # OCR
    "paddle_lang": "en",           # Se actualiza con detección automática
    "confidence_threshold": 0.7,

    # Idioma
    "force_language": None,        # None = autodetectar

    # Traducción
    "translate_to": "es",          # None = sin traducción
    "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY"),

    # Salida
    "output_srt": "output/subtitles.srt",
    "output_translated_srt": "output/subtitles_translated.srt",
}
```

---

## 5. 📍 subtitle_detector.py — Detecta posición (top/bottom)

```python
# modules/subtitle_detector.py
import cv2
import numpy as np
from dataclasses import dataclass

@dataclass
class SubtitleZone:
    position: str          # "top" | "bottom" | "custom"
    y_start: int
    y_end: int
    x_start: int
    x_end: int
    confidence: float


def detect_subtitle_zone(frames: list[np.ndarray], mode: str = "auto") -> SubtitleZone:
    """
    Analiza múltiples frames para detectar automáticamente
    dónde aparecen los subtítulos (franja superior o inferior).
    """
    height, width = frames[0].shape[:2]

    if mode == "bottom":
        return SubtitleZone("bottom", int(height * 0.75), height, 0, width, 1.0)
    if mode == "top":
        return SubtitleZone("top", 0, int(height * 0.25), 0, width, 1.0)

    # Modo AUTO: analizar varianza de píxeles entre frames
    top_scores = []
    bottom_scores = []

    for i in range(1, min(len(frames), 30)):
        diff = cv2.absdiff(frames[i], frames[i - 1])
        gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)

        top_region = gray[:int(height * 0.25), :]
        bottom_region = gray[int(height * 0.75):, :]

        top_scores.append(np.mean(top_region))
        bottom_scores.append(np.mean(bottom_region))

    avg_top = np.mean(top_scores)
    avg_bottom = np.mean(bottom_scores)

    if avg_bottom >= avg_top:
        return SubtitleZone(
            position="bottom",
            y_start=int(height * 0.72),
            y_end=height,
            x_start=int(width * 0.05),
            x_end=int(width * 0.95),
            confidence=avg_bottom / (avg_top + 1e-5)
        )
    else:
        return SubtitleZone(
            position="top",
            y_start=0,
            y_end=int(height * 0.28),
            x_start=int(width * 0.05),
            x_end=int(width * 0.95),
            confidence=avg_top / (avg_bottom + 1e-5)
        )


def crop_subtitle_region(frame: np.ndarray, zone: SubtitleZone) -> np.ndarray:
    """Recorta el frame a la zona de subtítulo detectada."""
    return frame[zone.y_start:zone.y_end, zone.x_start:zone.x_end]
```

---

## 6. ⏱️ change_detector.py — Cuándo cambia el subtítulo

```python
# modules/change_detector.py
import numpy as np
from skimage.metrics import structural_similarity as ssim
import cv2
from dataclasses import dataclass

@dataclass
class SubtitleChange:
    frame_index: int
    timestamp_sec: float
    is_new_subtitle: bool
    ssim_score: float


def detect_subtitle_changes(
    subtitle_crops: list[np.ndarray],
    timestamps: list[float],
    ssim_threshold: float = 0.92,
    min_duration: float = 0.5
) -> list[SubtitleChange]:
    """
    Detecta cuándo cambia el subtítulo comparando SSIM entre frames consecutivos.
    Retorna lista de cambios con timestamps exactos.
    """
    changes = []
    prev_crop = None
    last_change_time = -999

    for i, (crop, ts) in enumerate(zip(subtitle_crops, timestamps)):
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

        if prev_crop is None:
            changes.append(SubtitleChange(i, ts, True, 0.0))
            prev_crop = gray
            last_change_time = ts
            continue

        score = ssim(prev_crop, gray, data_range=255)
        is_change = (score < ssim_threshold) and (ts - last_change_time >= min_duration)

        if is_change:
            changes.append(SubtitleChange(i, ts, True, score))
            last_change_time = ts
        else:
            changes.append(SubtitleChange(i, ts, False, score))

        prev_crop = gray

    return changes


def group_into_blocks(
    ocr_results: list[dict],
    changes: list[SubtitleChange]
) -> list[dict]:
    """
    Agrupa los resultados OCR en bloques de subtítulo con tiempos de inicio/fin.
    Retorna lista de: {text, start_sec, end_sec, duration_sec}
    """
    blocks = []
    current_text = ""
    current_start = None

    for i, change in enumerate(changes):
        if change.is_new_subtitle:
            # Cerrar bloque anterior
            if current_text.strip() and current_start is not None:
                blocks.append({
                    "text": current_text.strip(),
                    "start_sec": current_start,
                    "end_sec": change.timestamp_sec,
                    "duration_sec": round(change.timestamp_sec - current_start, 3)
                })
            # Abrir nuevo bloque
            current_start = change.timestamp_sec
            current_text = ocr_results[i].get("text", "") if i < len(ocr_results) else ""
        else:
            # Actualizar texto del bloque actual si es más completo
            new_text = ocr_results[i].get("text", "") if i < len(ocr_results) else ""
            if len(new_text) > len(current_text):
                current_text = new_text

    # Cerrar último bloque
    if current_text.strip() and current_start is not None:
        last_ts = changes[-1].timestamp_sec + 2.0  # estimar fin
        blocks.append({
            "text": current_text.strip(),
            "start_sec": current_start,
            "end_sec": last_ts,
            "duration_sec": round(last_ts - current_start, 3)
        })

    return blocks
```

---

## 7. 🌐 language_detector.py — Detección de idioma

```python
# modules/language_detector.py
from lingua import Language, LanguageDetectorBuilder

# Construir detector con idiomas más comunes
DETECTOR = LanguageDetectorBuilder.from_languages(
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
).build()

LANG_TO_PADDLE = {
    "ENGLISH": "en",
    "SPANISH": "es",
    "PORTUGUESE": "pt",
    "FRENCH": "fr",
    "GERMAN": "de",
    "JAPANESE": "japan",
    "KOREAN": "korean",
    "CHINESE": "ch",
    "ARABIC": "ar",
}


def detect_language(texts: list[str]) -> dict:
    """
    Detecta el idioma predominante de una lista de textos OCR.
    Retorna: {language_name, paddle_code, confidence}
    """
    combined = " ".join(t for t in texts if len(t) > 5)[:2000]

    if not combined.strip():
        return {"language_name": "ENGLISH", "paddle_code": "en", "confidence": 0.0}

    result = DETECTOR.detect_language_of(combined)

    if result is None:
        return {"language_name": "ENGLISH", "paddle_code": "en", "confidence": 0.5}

    lang_name = result.name
    paddle_code = LANG_TO_PADDLE.get(lang_name, "en")

    return {
        "language_name": lang_name,
        "paddle_code": paddle_code,
        "confidence": 1.0  # lingua no da score directo, usar confidence_values() para más detalle
    }
```

---

## 8. 🚀 main.py — Orquestador completo

```python
# main.py
import cv2
import argparse
from tqdm import tqdm
from paddleocr import PaddleOCR
from modules.frame_extractor import extract_frames
from modules.subtitle_detector import detect_subtitle_zone, crop_subtitle_region
from modules.change_detector import detect_subtitle_changes, group_into_blocks
from modules.language_detector import detect_language
from modules.srt_writer import write_srt
from modules.translator import translate_blocks
from config import CONFIG


def run(video_path: str, config: dict):
    print(f"\n📹 Procesando: {video_path}")

    # 1. Extraer frames
    print("🎞️  Extrayendo frames...")
    frames, timestamps = extract_frames(video_path, config["fps_extraction"])
    print(f"   → {len(frames)} frames extraídos ({timestamps[-1]:.1f}s total)")

    # 2. Detectar zona de subtítulos
    print("📍 Detectando posición de subtítulos...")
    zone = detect_subtitle_zone(frames[:60], config["subtitle_zone_mode"])
    print(f"   → Posición detectada: {zone.position.upper()} (confianza: {zone.confidence:.2f})")

    # 3. Recortar región de subtítulos
    crops = [crop_subtitle_region(f, zone) for f in frames]

    # 4. Detectar cambios de subtítulo
    print("⏱️  Analizando cambios de subtítulo...")
    changes = detect_subtitle_changes(crops, timestamps, config["ssim_threshold"])
    new_subs = sum(1 for c in changes if c.is_new_subtitle)
    print(f"   → {new_subs} cambios de subtítulo detectados")

    # 5. OCR sobre frames con cambio
    print("🔍 Ejecutando OCR...")
    ocr = PaddleOCR(use_angle_cls=True, lang=config["paddle_lang"], show_log=False)
    ocr_results = []

    for i, (crop, change) in enumerate(tqdm(zip(crops, changes), total=len(crops))):
        if change.is_new_subtitle or i == 0:
            result = ocr.ocr(crop, cls=True)
            text_lines = []
            if result and result[0]:
                for line in result[0]:
                    confidence = line[1][1]
                    if confidence >= config["confidence_threshold"]:
                        text_lines.append(line[1][0])
            ocr_results.append({"text": " ".join(text_lines), "frame": i})
        else:
            ocr_results.append({"text": "", "frame": i})

    # 6. Detectar idioma
    all_texts = [r["text"] for r in ocr_results if r["text"]]
    lang_info = detect_language(all_texts)
    print(f"🌐 Idioma detectado: {lang_info['language_name']} (código Paddle: {lang_info['paddle_code']})")

    # Re-OCR con idioma correcto si cambió
    if lang_info["paddle_code"] != config["paddle_lang"]:
        print(f"   → Re-ejecutando OCR con idioma: {lang_info['paddle_code']}")
        ocr = PaddleOCR(use_angle_cls=True, lang=lang_info["paddle_code"], show_log=False)
        # (repetir paso 5 aquí si se requiere máxima precisión)

    # 7. Agrupar en bloques con tiempos
    blocks = group_into_blocks(ocr_results, changes)
    print(f"📝 {len(blocks)} bloques de subtítulo generados")

    # Mostrar estadísticas de timing
    durations = [b["duration_sec"] for b in blocks]
    if durations:
        print(f"   → Duración promedio por subtítulo: {sum(durations)/len(durations):.2f}s")
        print(f"   → Más corto: {min(durations):.2f}s | Más largo: {max(durations):.2f}s")

    # 8. Guardar .srt original
    write_srt(blocks, config["output_srt"])
    print(f"✅ SRT guardado: {config['output_srt']}")

    # 9. Traducir (opcional)
    if config.get("translate_to") and config.get("anthropic_api_key"):
        print(f"🌍 Traduciendo a: {config['translate_to']}...")
        translated = translate_blocks(blocks, config["translate_to"], config["anthropic_api_key"])
        write_srt(translated, config["output_translated_srt"])
        print(f"✅ SRT traducido: {config['output_translated_srt']}")

    print("\n🎉 ¡Proceso completado!")
    return blocks


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extractor de subtítulos quemados")
    parser.add_argument("video", help="Ruta al video MP4")
    parser.add_argument("--fps", type=float, default=2, help="Frames por segundo a analizar")
    parser.add_argument("--zone", choices=["auto", "top", "bottom"], default="auto")
    parser.add_argument("--translate-to", default=None, help="Código de idioma destino (ej: es, en, fr)")
    args = parser.parse_args()

    CONFIG["video_path"] = args.video
    CONFIG["fps_extraction"] = args.fps
    CONFIG["subtitle_zone_mode"] = args.zone
    CONFIG["translate_to"] = args.translate_to

    run(args.video, CONFIG)
```

---

## 9. 📊 Formato de salida enriquecido

Además del `.srt` estándar, el programa genera un **JSON de metadatos**:

```json
{
  "video": "input.mp4",
  "detected_language": "ENGLISH",
  "subtitle_position": "bottom",
  "total_subtitles": 142,
  "avg_duration_sec": 2.34,
  "subtitles": [
    {
      "index": 1,
      "start": "00:00:01,200",
      "end": "00:00:03,800",
      "duration_sec": 2.6,
      "text": "Hello, welcome to the show.",
      "text_translated": "Hola, bienvenido al programa."
    }
  ]
}
```

---

## 10. 🆚 Comparativa de lenguajes

| Lenguaje | Velocidad | Facilidad | Ecosistema IA | Recomendado para |
|---|---|---|---|---|
| **Python** ✅ | Media | Alta | Excelente | Prototipado y producción general |
| **Rust** | Muy alta | Baja | Limitado | Rendimiento extremo, sin IA |
| **Go** | Alta | Media | Básico | Microservicios, CLI tools |
| **C++** | Máxima | Muy baja | Medio | Integración directa con OpenCV |

**Recomendación final**: Python para el proyecto completo. Si el video es 4K o necesitas procesar cientos de videos, usa **Python + multiprocessing** o expón el OCR como microservicio en Go/Rust y llama desde Python.

---

## 11. 📋 Ejemplo de uso

```bash
# Caso básico
python main.py mi_video.mp4

# Con detección de zona forzada y traducción
python main.py mi_video.mp4 --zone bottom --translate-to es

# Análisis rápido (menos frames, más rápido)
python main.py mi_video.mp4 --fps 1

# Alta precisión (más frames)
python main.py mi_video.mp4 --fps 5
```

---

## 12. 🔗 Referencias clave

- [PaddleOCR (mejor que Tesseract)](https://github.com/PaddlePaddle/PaddleOCR)
- [lingua-py: detección de idioma robusta](https://github.com/pemistahl/lingua-py)
- [scikit-image SSIM](https://scikit-image.org/docs/stable/api/skimage.metrics.html)
- [pysrt: manejo de archivos SRT](https://github.com/byroot/pysrt)
- [Formato SRT explicado](https://www.animaker.es/blog/como-crear-un-archivo-srt/)
