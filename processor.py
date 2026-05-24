# processor.py
"""
Orquestador principal del pipeline de extracción de subtítulos.
Coordina todos los módulos en secuencia y reporta progreso via callbacks.
Diseñado para ejecutarse en un background thread.
"""

import os
import time
import logging
from typing import Callable, Optional

from config import DEFAULT_CONFIG, QUALITY_PRESETS
from modules.video_analyzer import analyze_video, video_info_to_dict
from modules.frame_extractor import extract_frames_streaming
from modules.subtitle_detector import detect_subtitle_zone, crop_subtitle_region
from modules.preprocessor import preprocess_subtitle_crop
from modules.change_detector import detect_subtitle_changes, group_into_blocks
from modules.ocr_engine import OCREngine
from modules.language_detector import detect_language
from modules.srt_writer import write_all_formats
from modules.translator import translate_blocks, check_libretranslate

logger = logging.getLogger(__name__)

# Pipeline stages with their weight in overall progress
STAGES = [
    ("analyzing", "Analizando video", 2),
    ("extracting", "Extrayendo frames", 18),
    ("detecting_zone", "Detectando zona de subtítulos", 5),
    ("preprocessing", "Preprocesando imágenes", 8),
    ("detecting_changes", "Detectando cambios", 10),
    ("ocr", "Ejecutando OCR", 40),
    ("detecting_language", "Detectando idioma", 2),
    ("grouping", "Generando subtítulos", 5),
    ("translating", "Traduciendo", 7),
    ("writing", "Guardando archivos", 3),
]


class SubtitleProcessor:
    """
    Procesa un video completo para extraer subtítulos quemados.
    Reporta progreso en tiempo real mediante un callback.
    """

    def __init__(self, job_id: str, video_path: str, output_dir: str, config: dict = None):
        self.job_id = job_id
        self.video_path = video_path
        self.output_dir = output_dir
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self._progress_callback: Optional[Callable] = None
        self._cancelled = False

        # Results stored here
        self.video_info = None
        self.blocks = []
        self.generated_files = {}
        self.stats = {}

    def set_progress_callback(self, callback: Callable):
        """Set callback: callback(stage_id, stage_name, percent, message)"""
        self._progress_callback = callback

    def cancel(self):
        """Cancel the processing."""
        self._cancelled = True

    def _report(self, stage_id: str, stage_name: str, percent: int, message: str):
        """Report progress to callback."""
        if self._progress_callback:
            # Calculate overall progress based on stage weights
            stage_idx = next((i for i, s in enumerate(STAGES) if s[0] == stage_id), 0)
            weight_before = sum(s[2] for s in STAGES[:stage_idx])
            current_weight = STAGES[stage_idx][2] if stage_idx < len(STAGES) else 0
            overall = weight_before + int(current_weight * percent / 100)

            self._progress_callback(stage_id, stage_name, overall, message)

    def process(self) -> dict:
        """
        Ejecuta el pipeline completo de extracción.

        Returns:
            dict con resultados: blocks, files, stats, video_info
        """
        start_time = time.time()
        os.makedirs(self.output_dir, exist_ok=True)

        try:
            # ── Stage 1: Analyze Video ────────────────────────────────────
            self._report("analyzing", "Analizando video", 0, "Leyendo metadatos del video...")
            self.video_info = analyze_video(self.video_path, self.output_dir)
            video_dict = video_info_to_dict(self.video_info)

            # Apply suggested preset if config is default
            if self.config.get("auto_preset", True):
                preset_name = self.video_info.suggested_preset
                if preset_name in QUALITY_PRESETS:
                    preset = QUALITY_PRESETS[preset_name]
                    for key, value in preset.items():
                        if key not in ("label", "description") and key not in self.config.get("_user_overrides", []):
                            self.config[key] = value

            self._report("analyzing", "Analizando video", 100,
                         f"Video: {self.video_info.width}x{self.video_info.height} "
                         f"| {self.video_info.duration_human} "
                         f"| Calidad: {self.video_info.quality_label}")

            if self._cancelled:
                return self._result("cancelled")

            # ── Stage 3: Detect Subtitle Zone (Muestra rápida para no cargar RAM) ───
            self._report("detecting_zone", "Detectando zona", 0, "Analizando posición del video...")
            import cv2
            cap = cv2.VideoCapture(self.video_path)
            total_vid_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            sample_frames = []
            if cap.isOpened() and total_vid_frames > 0:
                step = max(1, total_vid_frames // 40)
                for idx in range(40):
                    cap.set(cv2.CAP_PROP_POS_FRAMES, idx * step)
                    ret, frame = cap.read()
                    if not ret:
                        break
                    # downscale for fast detection
                    h, w = frame.shape[:2]
                    if min(h, w) > 540:
                        scale = 540 / min(h, w)
                        frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
                    sample_frames.append(frame)
            cap.release()

            zone = detect_subtitle_zone(
                sample_frames if sample_frames else [],
                mode=self.config["subtitle_zone_mode"],
                custom_zone=self.config.get("custom_zone"),
            )
            # Liberar muestra de inmediato
            del sample_frames
            import gc
            gc.collect()

            # Save zone preview
            if zone.preview_image is not None:
                preview_path = os.path.join(self.output_dir, "zone_preview.jpg")
                cv2.imwrite(preview_path, zone.preview_image)

            self._report("detecting_zone", "Detectando zona", 100,
                         f"Posición: {zone.position.upper()} (confianza: {zone.confidence:.1f})")

            if self._cancelled:
                return self._result("cancelled")

            # ── Stage 2: Extract & Preprocess (Ahorro RAM extremo) ───────────
            self._report("extracting", "Extrayendo frames", 0, "Iniciando extracción y recorte...")
            crops = []
            timestamps = []
            
            stream = extract_frames_streaming(
                self.video_path,
                fps_target=self.config["fps_extraction"],
                max_resolution=self.config.get("max_ocr_resolution", 540),
            )
            
            for frame, timestamp, extracted_count, estimated_total in stream:
                if self._cancelled:
                    break
                
                # Recortar zona inmediatamente (evita acumular la imagen gigante de pantalla completa)
                crop = crop_subtitle_region(frame, zone)
                
                # Preprocesar si está activado
                if self.config.get("preprocessing_enabled", False):
                    crop = preprocess_subtitle_crop(
                        crop,
                        upscale=self.config.get("preprocessing_upscale", False),
                        denoise=self.config.get("preprocessing_denoise", False),
                        sharpen=self.config.get("preprocessing_sharpen", False),
                        contrast=self.config.get("preprocessing_contrast", False),
                        binarize=self.config.get("preprocessing_binarize", False),
                    )
                
                crops.append(crop)
                timestamps.append(timestamp)
                
                if extracted_count % 30 == 0:
                    percent = min(99, int((extracted_count / max(estimated_total, 1)) * 100))
                    self._report("extracting", "Extrayendo y recortando", percent, 
                                 f"Frame {extracted_count}/{estimated_total} extraído ({timestamp:.1f}s)")
            
            self._report("extracting", "Extrayendo y recortando", 100, f"{len(crops)} frames procesados con éxito.")
            self._report("preprocessing", "Preprocesando", 100, "Preprocesamiento en tiempo real completado.")

            if self._cancelled:
                return self._result("cancelled")

            # ── Stage 5: Detect Changes ───────────────────────────────────
            self._report("detecting_changes", "Detectando cambios", 0, "Analizando SSIM...")
            changes = detect_subtitle_changes(
                crops, timestamps,
                ssim_threshold=self.config["ssim_threshold"],
                min_duration=self.config.get("min_subtitle_duration", 0.5),
                on_progress=lambda p, m: self._report("detecting_changes", "Detectando cambios", p, m),
            )
            new_subs = sum(1 for c in changes if c.is_new_subtitle)
            self._report("detecting_changes", "Detectando cambios", 100,
                         f"{new_subs} cambios de subtítulo detectados")

            if self._cancelled:
                return self._result("cancelled")

            # ── Stage 6: OCR ──────────────────────────────────────────────
            self._report("ocr", "Ejecutando OCR", 0, "Inicializando motor OCR...")
            ocr = OCREngine(
                engine=self.config.get("ocr_engine", "auto"),
                lang=self.config.get("paddle_lang", "en"),
                confidence_threshold=self.config["confidence_threshold"],
            )
            self._report("ocr", "Ejecutando OCR", 5,
                         f"Motor: {ocr.backend_name}")

            ocr_results = []
            ocr_count = sum(1 for c in changes if c.is_new_subtitle)
            ocr_done = 0

            for i, (crop, change) in enumerate(zip(crops, changes)):
                if change.is_new_subtitle or i == 0:
                    result = ocr.recognize(crop)
                    ocr_results.append(result)
                    ocr_done += 1
                    if ocr_done % 5 == 0:
                        self._report("ocr", "Ejecutando OCR",
                                     5 + int((ocr_done / max(ocr_count, 1)) * 95),
                                     f"OCR: {ocr_done}/{ocr_count} subtítulos procesados")
                else:
                    ocr_results.append({"text": "", "confidence": 0.0, "lines": []})

            self._report("ocr", "Ejecutando OCR", 100,
                         f"OCR completado: {ocr_count} subtítulos procesados con {ocr.backend_name}")

            if self._cancelled:
                return self._result("cancelled")

            # ── Stage 7: Detect Language ──────────────────────────────────
            self._report("detecting_language", "Detectando idioma", 0, "Analizando textos...")
            all_texts = [r["text"] for r in ocr_results if r["text"]]
            lang_info = detect_language(all_texts, self.config.get("force_language"))

            # Re-initialize OCR if language changed
            detected_lang = lang_info["language_code"]
            if detected_lang != self.config.get("paddle_lang", "en"):
                self._report("detecting_language", "Detectando idioma", 50,
                             f"Idioma: {lang_info['language_name']} — Re-inicializando OCR...")
                try:
                    ocr.change_language(detected_lang)
                    # Re-OCR the subtitle changes with correct language
                    for i, (crop, change) in enumerate(zip(crops, changes)):
                        if change.is_new_subtitle or i == 0:
                            ocr_results[i] = ocr.recognize(crop)
                except Exception as e:
                    logger.warning(f"No se pudo re-inicializar OCR para {detected_lang}: {e}")
                    self._report("detecting_language", "Detectando idioma", 75,
                                 "No se pudo cambiar el idioma OCR; usando resultados iniciales")

            self._report("detecting_language", "Detectando idioma", 100,
                         f"Idioma: {lang_info['language_name']} ({lang_info['confidence']:.0%})")

            if self._cancelled:
                return self._result("cancelled")

            # ── Stage 8: Group into blocks ────────────────────────────────
            self._report("grouping", "Generando subtítulos", 0, "Agrupando bloques...")
            self.blocks = group_into_blocks(ocr_results, changes)
            self._report("grouping", "Generando subtítulos", 100,
                         f"{len(self.blocks)} subtítulos generados")

            if self._cancelled:
                return self._result("cancelled")

            # ── Stage 9: Translate (optional) ─────────────────────────────
            if self.config.get("translate_enabled") and self.config.get("translate_to"):
                translate_url = self.config.get("libretranslate_url", "http://localhost:5000")
                if check_libretranslate(translate_url):
                    self._report("translating", "Traduciendo", 0,
                                 f"Traduciendo a {self.config['translate_to']}...")
                    self.blocks = translate_blocks(
                        self.blocks,
                        source_lang=detected_lang,
                        target_lang=self.config["translate_to"],
                        url=translate_url,
                        on_progress=lambda p, m: self._report("translating", "Traduciendo", p, m),
                    )
                    self._report("translating", "Traduciendo", 100, "Traducción completada")
                else:
                    self._report("translating", "Traduciendo", 100,
                                 "LibreTranslate no disponible — traducción omitida")
            else:
                self._report("translating", "Traduciendo", 100, "Traducción no solicitada")

            if self._cancelled:
                return self._result("cancelled")

            # ── Stage 10: Write files ─────────────────────────────────────
            self._report("writing", "Guardando archivos", 0, "Generando archivos de salida...")
            zone_info = {
                "position": zone.position,
                "y_start": zone.y_start,
                "y_end": zone.y_end,
                "confidence": round(zone.confidence, 2),
            }
            self.generated_files = write_all_formats(
                self.blocks,
                self.output_dir,
                base_name="subtitles",
                formats=self.config.get("output_formats", ["srt", "vtt", "json"]),
                video_info=video_dict,
                language_info=lang_info,
                zone_info=zone_info,
            )

            # Also write translated versions if available
            has_translation = any("text_translated" in b for b in self.blocks)
            if has_translation:
                translated_blocks = []
                for b in self.blocks:
                    tb = {**b, "text": b.get("text_translated", b["text"])}
                    translated_blocks.append(tb)
                write_all_formats(
                    translated_blocks,
                    self.output_dir,
                    base_name="subtitles_translated",
                    formats=self.config.get("output_formats", ["srt", "vtt"]),
                    video_info=video_dict,
                    language_info=lang_info,
                    zone_info=zone_info,
                )

            self._report("writing", "Guardando archivos", 100,
                         f"Archivos generados: {', '.join(self.generated_files.keys())}")

            # ── Done ──────────────────────────────────────────────────────
            elapsed = time.time() - start_time
            self.stats = {
                "total_subtitles": len(self.blocks),
                "processing_time_sec": round(elapsed, 1),
                "frames_analyzed": len(crops),
                "ocr_engine": ocr.backend_name,
                "language": lang_info,
                "zone": zone_info,
                "quality": self.video_info.quality_category,
                "has_translation": has_translation,
            }

            return self._result("completed")

        except Exception as e:
            logger.exception(f"Error processing job {self.job_id}")
            self._report("error", "Error", 0, str(e))
            return self._result("error", str(e))

    def _result(self, status: str, error: str = None) -> dict:
        """Build result dict."""
        return {
            "status": status,
            "job_id": self.job_id,
            "blocks": self.blocks,
            "files": self.generated_files,
            "stats": self.stats,
            "video_info": video_info_to_dict(self.video_info) if self.video_info else {},
            "error": error,
        }
