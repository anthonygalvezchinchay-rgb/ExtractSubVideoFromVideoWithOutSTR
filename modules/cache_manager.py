# modules/cache_manager.py
"""
MD5-based OCR result cache for on-demand subtitle recognition.

Avoids redundant OCR invocations when the user navigates back to a
previously-recognized frame/region.  Crops are normalised to a fixed
size and converted to grayscale before hashing so that minor scaling
differences don't cause cache misses.

Persistence:
  The cache is serialised to ``ocr_cache.json`` inside the job output
  directory and reloaded when the session resumes.
"""

import hashlib
import json
import logging
import os
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Standard dimensions for hash normalisation.
# Small enough to be fast, large enough to remain discriminative.
_HASH_WIDTH = 300
_HASH_HEIGHT = 60


class OCRCacheManager:
    """
    In-memory OCR result cache backed by an optional JSON file.

    Usage::

        cache = OCRCacheManager("/output/abc123/ocr_cache.json")

        hit = cache.get(cropped_bgr_image)
        if hit is None:
            result = ocr_engine.recognize(cropped_bgr_image)
            cache.set(cropped_bgr_image, result)
        else:
            result = hit
    """

    def __init__(self, cache_file_path: Optional[str] = None, max_entries: int = 5000):
        """
        Args:
            cache_file_path: Path to a JSON file for persistence.
                             Pass ``None`` for an ephemeral (memory-only) cache.
            max_entries:     Maximum entries before the oldest are evicted.
        """
        self.cache_file_path = cache_file_path
        self.max_entries = max_entries
        self._cache: dict[str, dict] = {}
        self._dirty = False

        if cache_file_path:
            self._load()

    # ── Public API ─────────────────────────────────────────────────────────

    def get(self, cropped_image: np.ndarray) -> Optional[dict]:
        """Return cached OCR result or ``None`` on miss."""
        h = self._compute_hash(cropped_image)
        return self._cache.get(h)

    def set(self, cropped_image: np.ndarray, ocr_result: dict):
        """Store an OCR result keyed by the crop's visual hash."""
        h = self._compute_hash(cropped_image)
        self._cache[h] = ocr_result
        self._dirty = True

        # Evict oldest entries if we exceed the cap
        if len(self._cache) > self.max_entries:
            excess = len(self._cache) - self.max_entries
            keys = list(self._cache.keys())[:excess]
            for k in keys:
                del self._cache[k]

    def flush(self):
        """Persist cache to disk if dirty."""
        if self._dirty and self.cache_file_path:
            self._save()
            self._dirty = False

    def clear(self):
        """Wipe all cached entries."""
        self._cache.clear()
        self._dirty = True

    @property
    def size(self) -> int:
        return len(self._cache)

    # ── Hashing ────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_hash(image: np.ndarray) -> str:
        """
        Compute a deterministic MD5 hex digest from a BGR crop.

        The image is first resized to ``_HASH_WIDTH x _HASH_HEIGHT`` and
        converted to grayscale so that minor colour or resolution
        variations between frames don't invalidate the cache.
        """
        # Resize to fixed dimensions
        normalised = cv2.resize(image, (_HASH_WIDTH, _HASH_HEIGHT), interpolation=cv2.INTER_AREA)
        # Convert to single-channel grayscale
        if len(normalised.shape) == 3:
            normalised = cv2.cvtColor(normalised, cv2.COLOR_BGR2GRAY)
        return hashlib.md5(normalised.tobytes()).hexdigest()

    # ── Persistence ────────────────────────────────────────────────────────

    def _load(self):
        """Load cache from JSON file."""
        if not self.cache_file_path or not os.path.isfile(self.cache_file_path):
            return
        try:
            with open(self.cache_file_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                self._cache = data
                logger.info(f"OCR cache loaded: {len(self._cache)} entries from {self.cache_file_path}")
        except Exception as exc:
            logger.warning(f"Failed to load OCR cache: {exc}")

    def _save(self):
        """Persist cache to JSON file."""
        if not self.cache_file_path:
            return
        try:
            os.makedirs(os.path.dirname(self.cache_file_path) or ".", exist_ok=True)
            with open(self.cache_file_path, "w", encoding="utf-8") as fh:
                json.dump(self._cache, fh, ensure_ascii=False, indent=2)
            logger.info(f"OCR cache saved: {len(self._cache)} entries to {self.cache_file_path}")
        except Exception as exc:
            logger.warning(f"Failed to save OCR cache: {exc}")

    def __del__(self):
        try:
            self.flush()
        except Exception:
            pass
