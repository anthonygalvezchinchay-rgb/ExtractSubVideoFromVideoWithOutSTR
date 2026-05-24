# server.py
"""
FastAPI backend server for SubtitleForge.
Provides REST API, WebSocket for real-time progress, and serves the frontend.
"""

import os
import asyncio
import json
import logging
import shutil
import importlib.util
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from config import SERVER_CONFIG, DEFAULT_CONFIG, QUALITY_PRESETS, SUPPORTED_LANGUAGES
from modules.video_analyzer import analyze_video, video_info_to_dict
from modules.translator import check_libretranslate, translate_text
from modules.video_decoder import VideoDecoder
from modules.cache_manager import OCRCacheManager
from modules.ocr_engine import OCREngine
from modules.preprocessor import preprocess_subtitle_crop
from job_manager import JobManager

# ─── Setup ────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="SubtitleForge", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure directories exist
for dir_key in ("upload_dir", "output_dir", "temp_dir"):
    os.makedirs(SERVER_CONFIG[dir_key], exist_ok=True)

job_manager = JobManager()

# ─── Persistent Interactive Sessions ──────────────────────────────────────────
# Maps job_id → VideoDecoder  (kept alive for interactive seeking)
_active_decoders: dict[str, VideoDecoder] = {}
# Maps job_id → OCRCacheManager
_active_caches: dict[str, OCRCacheManager] = {}
# Maps job_id → OCREngine (lazy‐initialised, reused across requests)
_active_ocr_engines: dict[str, OCREngine] = {}

# ─── API Endpoints ────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    """Health check — also reports system capabilities."""
    libre_available = check_libretranslate()

    # Keep health lightweight: importing Paddle/Torch can take several seconds.
    ocr_engines = [
        name for name in ("paddleocr", "easyocr")
        if importlib.util.find_spec(name) is not None
    ]
    gpu_info = "available at processing time" if importlib.util.find_spec("paddle") else "CPU"

    return {
        "status": "ok",
        "libretranslate_available": libre_available,
        "ocr_engines": ocr_engines,
        "gpu": gpu_info,
        "supported_languages": SUPPORTED_LANGUAGES,
        "quality_presets": {k: {"label": v["label"], "description": v["description"]}
                          for k, v in QUALITY_PRESETS.items()},
    }


@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    """Upload a video file. Returns job_id and video analysis."""
    # Validate extension
    ext = Path(file.filename).suffix.lower()
    if ext not in SERVER_CONFIG["allowed_extensions"]:
        raise HTTPException(400, f"Formato no soportado: {ext}. Usa: {', '.join(SERVER_CONFIG['allowed_extensions'])}")

    # Save file
    job_id = job_manager.create_job("")  # temp, will update path
    upload_path = os.path.join(SERVER_CONFIG["upload_dir"], f"{job_id}{ext}")

    try:
        with open(upload_path, "wb") as f:
            while chunk := await file.read(1024 * 1024):  # 1MB chunks
                f.write(chunk)
    except Exception as e:
        raise HTTPException(500, f"Error guardando archivo: {e}")

    # Update job with actual path
    job = job_manager._jobs.get(job_id)
    if job:
        job.video_path = upload_path

    # Analyze video
    try:
        output_dir = os.path.join(SERVER_CONFIG["output_dir"], job_id)
        video_info = analyze_video(upload_path, output_dir)
        video_dict = video_info_to_dict(video_info)
    except Exception as e:
        logger.exception("Error analyzing video")
        video_dict = {"error": str(e)}

    return {
        "job_id": job_id,
        "video_info": video_dict,
        "suggested_preset": video_dict.get("suggested_preset", "medium"),
        "default_config": DEFAULT_CONFIG,
    }


@app.post("/api/process/{job_id}")
async def start_processing(job_id: str, config: dict = None):
    """Start processing a previously uploaded video."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job no encontrado")

    user_config = config or {}
    # Mark user overrides so auto-preset doesn't override them
    if user_config:
        user_config["_user_overrides"] = list(user_config.keys())

    try:
        job_manager.start_job(job_id, user_config)
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {"status": "processing", "job_id": job_id}


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    """Get current job status (polling fallback for WebSocket)."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job no encontrado")
    return job


@app.get("/api/results/{job_id}")
async def get_results(job_id: str):
    """Get processing results."""
    result = job_manager.get_results(job_id)
    if not result:
        raise HTTPException(404, "Resultados no disponibles")
    return result


@app.get("/api/download/{job_id}/{format}")
async def download_file(job_id: str, format: str):
    """Download subtitle file in specified format."""
    output_dir = os.path.join(SERVER_CONFIG["output_dir"], job_id)

    # Check for translated version first
    translated_path = os.path.join(output_dir, f"subtitles_translated.{format}")
    original_path = os.path.join(output_dir, f"subtitles.{format}")

    filepath = translated_path if os.path.exists(translated_path) else original_path

    if not os.path.exists(filepath):
        raise HTTPException(404, f"Archivo .{format} no encontrado")

    return FileResponse(
        filepath,
        filename=os.path.basename(filepath),
        media_type="application/octet-stream",
    )


@app.get("/api/download-original/{job_id}/{format}")
async def download_original_file(job_id: str, format: str):
    """Download the original (non-translated) subtitle file."""
    filepath = os.path.join(SERVER_CONFIG["output_dir"], job_id, f"subtitles.{format}")
    if not os.path.exists(filepath):
        raise HTTPException(404, f"Archivo .{format} no encontrado")
    return FileResponse(filepath, filename=f"subtitles_original.{format}")


@app.get("/api/thumbnail/{job_id}")
async def get_thumbnail(job_id: str):
    """Get video thumbnail."""
    thumb_path = os.path.join(SERVER_CONFIG["output_dir"], job_id, "thumbnail.jpg")
    if not os.path.exists(thumb_path):
        raise HTTPException(404, "Thumbnail no disponible")
    return FileResponse(thumb_path, media_type="image/jpeg")


@app.get("/api/zone-preview/{job_id}")
async def get_zone_preview(job_id: str):
    """Get subtitle zone detection preview image."""
    preview_path = os.path.join(SERVER_CONFIG["output_dir"], job_id, "zone_preview.jpg")
    if not os.path.exists(preview_path):
        raise HTTPException(404, "Preview no disponible")
    return FileResponse(preview_path, media_type="image/jpeg")


@app.get("/api/video/{job_id}")
async def stream_video(job_id: str):
    """Stream the uploaded video."""
    job = job_manager._jobs.get(job_id)
    if not job or not os.path.exists(job.video_path):
        raise HTTPException(404, "Video no encontrado")
    return FileResponse(job.video_path, media_type="video/mp4")


@app.get("/api/subtitles-vtt/{job_id}")
async def get_subtitles_vtt(job_id: str):
    """Get VTT subtitles for HTML5 video player."""
    vtt_path = os.path.join(SERVER_CONFIG["output_dir"], job_id, "subtitles.vtt")
    if not os.path.exists(vtt_path):
        raise HTTPException(404, "VTT no disponible")
    return FileResponse(vtt_path, media_type="text/vtt")


@app.delete("/api/job/{job_id}")
async def delete_job(job_id: str):
    """Delete a job and its files."""
    job_manager.delete_job(job_id)
    return {"status": "deleted"}


@app.post("/api/cancel/{job_id}")
async def cancel_job(job_id: str):
    """Cancel a running job."""
    job_manager.cancel_job(job_id)
    return {"status": "cancelled"}


# ─── Interactive Subtitle Authoring API ───────────────────────────────────────

@app.get("/api/video/session/{job_id}")
async def init_video_session(job_id: str):
    """Open a persistent video decoder and return video metadata."""
    job = job_manager._jobs.get(job_id)
    if not job or not os.path.exists(job.video_path):
        raise HTTPException(404, "Video no encontrado")

    # Reuse existing decoder or create new one
    if job_id not in _active_decoders:
        try:
            decoder = VideoDecoder(job.video_path)
            _active_decoders[job_id] = decoder
        except Exception as e:
            raise HTTPException(500, f"Error abriendo video: {e}")

    # Ensure cache manager exists
    if job_id not in _active_caches:
        cache_path = os.path.join(SERVER_CONFIG["output_dir"], job_id, "ocr_cache.json")
        _active_caches[job_id] = OCRCacheManager(cache_path)

    decoder = _active_decoders[job_id]
    return {
        "job_id": job_id,
        "video": decoder.get_metadata(),
    }


@app.get("/api/video/{job_id}/frame/{frame_idx}")
async def get_video_frame(job_id: str, frame_idx: int):
    """Decode and return a specific frame as JPEG."""
    decoder = _active_decoders.get(job_id)
    if not decoder:
        raise HTTPException(404, "Session no activa. Usa /api/video/session/{job_id} primero.")

    try:
        frame_bgr, timestamp = decoder.get_frame(frame_idx)
    except Exception as e:
        raise HTTPException(500, f"Error decodificando frame {frame_idx}: {e}")

    # Encode as JPEG and stream
    import cv2
    _, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
    from fastapi.responses import Response
    return Response(
        content=buf.tobytes(),
        media_type="image/jpeg",
        headers={
            "X-Frame-Index": str(frame_idx),
            "X-Timestamp": f"{timestamp:.4f}",
            "Cache-Control": "public, max-age=60",
        },
    )


@app.post("/api/ocr/process-frame")
async def ocr_process_frame(payload: dict):
    """
    On-demand OCR: decode frame → crop region → preprocess → OCR → cache.

    Payload::
        {
            "job_id": str,
            "frame_idx": int,
            "region": [y1_norm, x1_norm, y2_norm, x2_norm],   // 0-1 normalised
            "config": {"engine": "auto", "lang": "ja", ...}    // optional
        }
    """
    job_id = payload.get("job_id")
    frame_idx = payload.get("frame_idx", 0)
    region = payload.get("region")   # [y1, x1, y2, x2] normalised
    user_config = payload.get("config", {})

    decoder = _active_decoders.get(job_id)
    if not decoder:
        raise HTTPException(404, "Session no activa.")

    # Decode frame
    try:
        frame_bgr, timestamp = decoder.get_frame(frame_idx)
    except Exception as e:
        raise HTTPException(500, f"Error decodificando frame: {e}")

    # Crop region
    h, w = frame_bgr.shape[:2]
    if region and len(region) == 4:
        y1 = int(region[0] * h)
        x1 = int(region[1] * w)
        y2 = int(region[2] * h)
        x2 = int(region[3] * w)
        crop = frame_bgr[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
    else:
        # Default: bottom 25%
        crop = frame_bgr[int(h * 0.75):h, :]

    # Check cache
    cache = _active_caches.get(job_id)
    if cache:
        cached = cache.get(crop)
        if cached:
            return {**cached, "cached": True, "frame_idx": frame_idx, "timestamp": timestamp}

    # Preprocess
    preprocessing = user_config.get("preprocessing", {})
    if any(preprocessing.values()) if preprocessing else False:
        crop = preprocess_subtitle_crop(
            crop,
            upscale=preprocessing.get("upscale", False),
            denoise=preprocessing.get("denoise", False),
            sharpen=preprocessing.get("sharpen", False),
            contrast=preprocessing.get("contrast", True),
            binarize=preprocessing.get("binarize", False),
            padding=preprocessing.get("padding", True),
        )

    # Get or create OCR engine for this session
    engine_name = user_config.get("engine", "auto")
    lang = user_config.get("lang", "ja")  # Default to ja for anime context

    existing_engine = _active_ocr_engines.get(job_id)
    if not existing_engine or existing_engine.engine_name != engine_name or existing_engine.lang != lang:
        _active_ocr_engines[job_id] = OCREngine(engine=engine_name, lang=lang, lazy=True)

    ocr = _active_ocr_engines[job_id]
    result = ocr.recognize(crop)
    result["cached"] = False
    result["frame_idx"] = frame_idx
    result["timestamp"] = timestamp

    # Store in cache
    if cache:
        cache.set(crop, {"text": result["text"], "confidence": result["confidence"], "lines": result["lines"]})
        cache.flush()

    return result


@app.post("/api/subtitle/save-job")
async def save_subtitle_blocks(payload: dict):
    """Persist the current list of subtitle blocks to disk."""
    job_id = payload.get("job_id")
    blocks = payload.get("blocks", [])
    region = payload.get("region")  # optional persisted region

    if not job_id:
        raise HTTPException(400, "job_id requerido")

    output_dir = os.path.join(SERVER_CONFIG["output_dir"], job_id)
    os.makedirs(output_dir, exist_ok=True)

    import json
    save_data = {
        "version": "2.0",
        "generator": "SubtitleForge (Manual Assist)",
        "job_id": job_id,
        "region": region,
        "total_subtitles": len(blocks),
        "subtitles": blocks,
    }
    save_path = os.path.join(output_dir, "subtitles_session.json")
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)

    return {"status": "saved", "path": save_path, "count": len(blocks)}


@app.get("/api/subtitle/load-job/{job_id}")
async def load_subtitle_blocks(job_id: str):
    """Load previously saved subtitle blocks."""
    import json
    save_path = os.path.join(SERVER_CONFIG["output_dir"], job_id, "subtitles_session.json")
    if not os.path.exists(save_path):
        return {"subtitles": [], "region": None}
    with open(save_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


@app.get("/api/subtitle/export/{job_id}/{fmt}")
async def export_subtitles(job_id: str, fmt: str):
    """Export subtitle blocks to SRT/VTT/JSON/ASS."""
    import json as json_mod
    from modules.srt_writer import write_all_formats

    save_path = os.path.join(SERVER_CONFIG["output_dir"], job_id, "subtitles_session.json")
    if not os.path.exists(save_path):
        raise HTTPException(404, "No hay subtítulos guardados.")

    with open(save_path, "r", encoding="utf-8") as f:
        data = json_mod.load(f)

    blocks = data.get("subtitles", [])
    if not blocks:
        raise HTTPException(400, "Lista de subtítulos vacía.")

    # Normalise block keys for the writer (map new model → legacy keys)
    legacy_blocks = []
    for b in blocks:
        legacy_blocks.append({
            "index": b.get("index", 0),
            "text": b.get("text_original", b.get("text", "")),
            "text_translated": b.get("text_translated", ""),
            "start_sec": b.get("start_time", 0),
            "end_sec": b.get("end_time", 0),
            "duration_sec": round(b.get("end_time", 0) - b.get("start_time", 0), 3),
            "confidence": b.get("ocr_confidence", 0),
        })

    output_dir = os.path.join(SERVER_CONFIG["output_dir"], job_id)
    generated = write_all_formats(legacy_blocks, output_dir, formats=[fmt])

    if fmt not in generated:
        raise HTTPException(400, f"Formato '{fmt}' no soportado.")

    return FileResponse(
        generated[fmt],
        filename=os.path.basename(generated[fmt]),
        media_type="application/octet-stream",
    )


@app.post("/api/translate-line")
async def translate_single_line(payload: dict):
    """Translate a single subtitle line via LibreTranslate."""
    text = payload.get("text", "")
    source = payload.get("source", "auto")
    target = payload.get("target", "es")
    url = payload.get("url", "http://localhost:5000")

    if not text.strip():
        return {"translated": ""}

    translated = translate_text(text, source, target, url)
    return {"translated": translated}


# ─── WebSocket ────────────────────────────────────────────────────────────────

@app.websocket("/ws/{job_id}")
async def websocket_progress(websocket: WebSocket, job_id: str):
    """WebSocket endpoint for real-time progress updates."""
    await websocket.accept()
    logger.info(f"WebSocket connected for job {job_id}")

    queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def on_update(data):
        loop.call_soon_threadsafe(queue.put_nowait, data)

    job_manager.register_ws_callback(job_id, on_update)

    try:
        while True:
            try:
                data = await asyncio.wait_for(queue.get(), timeout=30)
                await websocket.send_json(data)
                if data.get("type") == "completed":
                    break
            except asyncio.TimeoutError:
                # Send heartbeat to keep connection alive
                await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for job {job_id}")
    except Exception as e:
        logger.warning(f"WebSocket error for job {job_id}: {e}")
    finally:
        job_manager.unregister_ws_callback(job_id, on_update)


# ─── Serve Frontend ──────────────────────────────────────────────────────────

frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n🎬 SubtitleForge Server")
    print(f"   → http://localhost:{SERVER_CONFIG['port']}")
    print(f"   → Upload dir: {SERVER_CONFIG['upload_dir']}")
    print(f"   → Output dir: {SERVER_CONFIG['output_dir']}\n")
    uvicorn.run(
        app,
        host=SERVER_CONFIG["host"],
        port=SERVER_CONFIG["port"],
        log_level="info",
    )
