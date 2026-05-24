# job_manager.py
"""
Gestión de jobs de procesamiento en background.
Para uso personal (single user) — almacena estado en memoria.
"""

import os
import shutil
import threading
import time
import uuid
import logging
from typing import Callable, Optional
from datetime import datetime

from processor import SubtitleProcessor
from config import SERVER_CONFIG

logger = logging.getLogger(__name__)


class Job:
    """Representa un job de procesamiento."""

    def __init__(self, job_id: str, video_path: str, output_dir: str):
        self.job_id = job_id
        self.video_path = video_path
        self.output_dir = output_dir
        self.status = "pending"  # pending, processing, completed, error, cancelled
        self.created_at = datetime.now()
        self.started_at = None
        self.completed_at = None
        self.current_stage = ""
        self.current_stage_name = ""
        self.progress = 0
        self.message = ""
        self.result = None
        self.error = None
        self._processor: Optional[SubtitleProcessor] = None
        self._thread: Optional[threading.Thread] = None


class JobManager:
    """Gestiona la cola y ejecución de jobs de procesamiento."""

    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._ws_callbacks: dict[str, list[Callable]] = {}  # job_id -> list of callbacks

    def create_job(self, video_path: str) -> str:
        """Crea un nuevo job y retorna su ID."""
        job_id = str(uuid.uuid4())[:8]
        output_dir = os.path.join(SERVER_CONFIG["output_dir"], job_id)
        os.makedirs(output_dir, exist_ok=True)

        job = Job(job_id, video_path, output_dir)
        with self._lock:
            self._jobs[job_id] = job

        return job_id

    def start_job(self, job_id: str, config: dict = None):
        """Inicia el procesamiento de un job en background thread."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise ValueError(f"Job {job_id} no encontrado")
            if job.status == "processing":
                raise ValueError(f"Job {job_id} ya está en proceso")

        processor = SubtitleProcessor(job_id, job.video_path, job.output_dir, config)
        job._processor = processor

        def progress_callback(stage_id, stage_name, percent, message):
            job.current_stage = stage_id
            job.current_stage_name = stage_name
            job.progress = percent
            job.message = message
            self._notify_ws(job_id, {
                "type": "progress",
                "stage": stage_id,
                "stage_name": stage_name,
                "percent": percent,
                "message": message,
            })

        processor.set_progress_callback(progress_callback)

        def run():
            job.status = "processing"
            job.started_at = datetime.now()
            try:
                result = processor.process()
                job.result = result
                job.status = result.get("status", "completed")
                if result.get("status") == "error":
                    job.error = result.get("error")
            except Exception as e:
                job.status = "error"
                job.error = str(e)
                logger.exception(f"Job {job_id} failed")
            finally:
                job.completed_at = datetime.now()
                self._notify_ws(job_id, {
                    "type": "completed",
                    "status": job.status,
                    "result": job.result,
                    "error": job.error,
                })

        thread = threading.Thread(target=run, daemon=True)
        job._thread = thread
        thread.start()

    def cancel_job(self, job_id: str):
        """Cancela un job en proceso."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job and job._processor:
                job._processor.cancel()
                job.status = "cancelled"

    def get_job(self, job_id: str) -> Optional[dict]:
        """Retorna el estado actual de un job."""
        job = self._jobs.get(job_id)
        if not job:
            return None
        return {
            "job_id": job.job_id,
            "status": job.status,
            "progress": job.progress,
            "current_stage": job.current_stage,
            "current_stage_name": job.current_stage_name,
            "message": job.message,
            "created_at": job.created_at.isoformat(),
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "error": job.error,
        }

    def get_results(self, job_id: str) -> Optional[dict]:
        """Retorna los resultados de un job completado."""
        job = self._jobs.get(job_id)
        if not job or not job.result:
            return None
        return job.result

    def register_ws_callback(self, job_id: str, callback: Callable):
        """Registra un callback de WebSocket para un job."""
        if job_id not in self._ws_callbacks:
            self._ws_callbacks[job_id] = []
        self._ws_callbacks[job_id].append(callback)

    def unregister_ws_callback(self, job_id: str, callback: Callable):
        """Elimina un callback de WebSocket."""
        if job_id in self._ws_callbacks:
            self._ws_callbacks[job_id] = [
                cb for cb in self._ws_callbacks[job_id] if cb != callback
            ]

    def _notify_ws(self, job_id: str, data: dict):
        """Notifica a todos los WebSocket listeners de un job."""
        for callback in self._ws_callbacks.get(job_id, []):
            try:
                callback(data)
            except Exception as e:
                logger.warning(f"WS callback error: {e}")

    def cleanup_old_jobs(self, max_age_hours: int = 24):
        """Limpia jobs antiguos y sus archivos."""
        now = datetime.now()
        to_delete = []
        for job_id, job in self._jobs.items():
            if job.completed_at:
                age = (now - job.completed_at).total_seconds() / 3600
                if age > max_age_hours:
                    to_delete.append(job_id)

        from server import _active_decoders, _active_caches, _active_ocr_engines
        for job_id in to_delete:
            decoder = _active_decoders.pop(job_id, None)
            if decoder:
                try:
                    decoder.close()
                except Exception:
                    pass
            _active_caches.pop(job_id, None)
            _active_ocr_engines.pop(job_id, None)

            job = self._jobs.pop(job_id, None)
            if job and os.path.exists(job.output_dir):
                shutil.rmtree(job.output_dir, ignore_errors=True)
            logger.info(f"Cleaned up job {job_id}")

    def delete_job(self, job_id: str):
        """Elimina un job, sus decodificadores activos y sus archivos."""
        # Clean up active interactive session resources
        from server import _active_decoders, _active_caches, _active_ocr_engines
        decoder = _active_decoders.pop(job_id, None)
        if decoder:
            try:
                decoder.close()
            except Exception:
                pass
        _active_caches.pop(job_id, None)
        _active_ocr_engines.pop(job_id, None)

        job = self._jobs.pop(job_id, None)
        if job:
            if os.path.exists(job.output_dir):
                shutil.rmtree(job.output_dir, ignore_errors=True)
            if os.path.exists(job.video_path):
                try:
                    os.remove(job.video_path)
                except Exception:
                    pass
