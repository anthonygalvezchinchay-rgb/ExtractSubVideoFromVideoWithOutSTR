# Technical Design: Human-Assisted Subtitle Authoring

This document outlines the architectural changes, data models, service patterns, and technology selections to implement the manual-assist fansub editing system.

---

## 1. Project Directory Structure
To support clean separation between video processing, OCR engines, and subtitle services, we will organize the backend into a modular layout:

```
/home/antoni/Downloads/BB/
├── config.py                  # Global settings, OCR engine paths, and cache limits
├── server.py                  # FastAPI router, REST APIs, and WebSocket endpoints
├── job_manager.py             # Manages persistent video sessions and active jobs
├── modules/
│   ├── ocr_engine.py          # Unified OCR Engine wrapper (PaddleOCR, EasyOCR, Tesseract, MangaOCR)
│   ├── video_decoder.py       # Frame-exact PyAV / OpenCV random-access service [NEW]
│   ├── cache_manager.py       # MD5-based crop region OCR cache [NEW]
│   ├── preprocessor.py        # Image filters (CLAHE, Otsu, Padding, Upscaling)
│   ├── srt_writer.py          # Subtitle exporter (.srt, .vtt, .json, .ass) [UPDATED]
│   └── auto_assist.py         # SSIM change detection helper (archived modules) [UPDATED]
└── frontend/
    ├── index.html             # Fansub layout (Left: Player, Right: Editor, Bottom: Timeline)
    ├── styles.css             # Glassmorphic grid, dark theme, interactive timeline styles
    └── app.js                 # ES6 Core, Canvas Renderer, Hotkey Manager, Timeline Controller
```

---

## 2. Backend Design

### A. Persistent Frame-Exact Video Decoder (`modules/video_decoder.py`)
To avoid drift and provide low-latency seeking, we will implement a `VideoDecoder` class backed by **PyAV** (Python bindings for FFmpeg libraries) as the primary option, with a fallback to a persistent **OpenCV VideoCapture** instance.

```python
import av
import cv2
from typing import Optional, Tuple
import numpy as np

class VideoDecoder:
    """Provides frame-exact seeking and decodes specific frames on-demand."""
    def __init__(self, video_path: str):
        self.video_path = video_path
        self.container = av.open(video_path)
        self.stream = self.container.streams.video[0]
        self.fps = float(self.stream.average_rate)
        self.total_frames = self.stream.frames or int(self.stream.duration * self.fps / self.stream.time_base.denominator)
        self.width = self.stream.width
        self.height = self.stream.height
        
    def get_frame(self, frame_index: int) -> Tuple[np.ndarray, float]:
        """
        Seeks directly to frame_index and returns the BGR image + timestamp in seconds.
        Uses keyframe seeking + decoding discard loop to ensure frame accuracy.
        """
        # Calculate target timestamp in stream time base
        time_base = self.stream.time_base
        target_sec = frame_index / self.fps
        pts = int(target_sec / time_base)
        
        # Seek to the nearest keyframe before target pts
        self.container.seek(pts, stream=self.stream)
        
        # Decode packets until reaching the exact target frame index
        for frame in self.container.decode(video=0):
            current_idx = int(frame.time * self.fps)
            if current_idx >= frame_index:
                # Convert PyAV frame to OpenCV BGR format
                img = frame.to_ndarray(format='bgr24')
                return img, frame.time
                
        # Fallback to OpenCV if PyAV seeking fails
        return self._get_frame_opencv(frame_index)

    def _get_frame_opencv(self, frame_index: int) -> Tuple[np.ndarray, float]:
        cap = cv2.VideoCapture(self.video_path)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            raise RuntimeError(f"Could not decode frame {frame_index}")
        return frame, frame_index / self.fps
```

### B. Subtitle Data Model (`modules/subtitle_model.py` / Dictionary)
The new `SubtitleBlock` encapsulates editing metadata, user overrides, and caching information:

```python
{
    "index": int,                # 1-based sequential identifier
    "start_time": float,         # Start timestamp in seconds
    "end_time": float,           # End timestamp in seconds
    "start_frame": int,          # Start frame index
    "end_frame": int,            # End frame index
    "text_original": str,        # Raw OCR output
    "text_translated": str,      # Optional translation output
    "ocr_confidence": float,     # Confidence score returned by the engine (0.0 - 1.0)
    "cached": bool,              # True if retrieved from OCR cache
    "region": list[float],       # Bounding box coords normalized: [y1, x1, y2, x2]
    "edited_by_user": bool       # True if the user manually modified the text
}
```

### C. On-Demand OCR Cache (`modules/cache_manager.py`)
To prevent duplicate OCR invocations when navigating back and forth over the same subtitle lines, we introduce `OCRCacheManager`.
* **Hash Calculation:** Crop regions are converted to a standard shape (e.g. 80px high), converted to grayscale, and hashed via MD5 on their raw byte array.
* **Storage:** In-memory dictionary written asynchronously to `/output/{job_id}/ocr_cache.json`.

```python
import hashlib
import json
import os
import cv2
import numpy as np

class OCRCacheManager:
    def __init__(self, cache_file_path: str):
        self.cache_file_path = cache_file_path
        self.cache = {}
        self.load_cache()

    def _compute_hash(self, cropped_image: np.ndarray) -> str:
        # Normalize size to avoid subtle sizing mismatches triggering cache misses
        normalized = cv2.resize(cropped_image, (300, 60))
        gray = cv2.cvtColor(normalized, cv2.COLOR_BGR2GRAY)
        return hashlib.md5(gray.tobytes()).hexdigest()

    def get(self, cropped_image: np.ndarray) -> Optional[dict]:
        h = self._compute_hash(cropped_image)
        return self.cache.get(h)

    def set(self, cropped_image: np.ndarray, ocr_result: dict):
        h = self._compute_hash(cropped_image)
        self.cache[h] = ocr_result
        self.save_cache()

    def load_cache(self):
        if os.path.exists(self.cache_file_path):
            with open(self.cache_file_path, "r", encoding="utf-8") as f:
                self.cache = json.load(f)

    def save_cache(self):
        with open(self.cache_file_path, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, indent=2, ensure_ascii=False)
```

### D. Japanese & Stylized Text OCR Optimizations
1. **Engine Selection:**
   * **PaddleOCR JP (`lang="japan"`)**: Default recommendation. Extremely precise on rotated/vertical Japanese texts, handles standard mincho and gothic fonts with DB detection models.
   * **EasyOCR JP (`lang_list=['ja', 'en']`)**: Good fallback but heavier on VRAM.
   * **MangaOCR (Optional Plugin)**: Visions-based Transformer (`manga-ocr` on PyPI). Exceptional at handwriting, stylized outlines, and manga fonts. We will add a lazy import wrapper to support it if installed in the environment.
2. **Outlined/Stylized Text Preprocessing:**
   * *CLAHE Contrast Filter:* Evens out complex backgrounds in anime video frames.
   * *Otsu Threshold Binarization:* Isolates solid high-contrast text cores from dark outlines.
   * *Padding:* Adds 10px white padding around cropped areas, preventing OCR edge-cutting bugs.

---

## 3. Frontend Design (Fansub-Style UI Layout)

### A. Layout Grid & Components
The screen will be partitioned into three interactive spaces built using vanilla CSS Grid:

```
┌───────────────────────────────────────┬──────────────────────────────┐
│                                       │                              │
│             LEFT CONTAINER            │       RIGHT CONTAINER        │
│                                       │                              │
│       [ Frame-Exact Canvas Player ]   │      [ Subtitle Editor ]     │
│       - Bounding Box Selector overlay │      - Active original text  │
│                                       │      - Active translation    │
│       [ Timing Controls & Badges ]    │      - OCR Trigger Button    │
│       - Frame index / current time    │                              │
│       - Region coords persistence     │      [ Subtitle Blocks List] │
│                                       │      - List with indexes     │
│                                       │      - Click to seek frame   │
│                                       │                              │
├───────────────────────────────────────┴──────────────────────────────┤
│                            BOTTOM CONTAINER                          │
│                                                                      │
│                      [ Interactive Timeline Grid ]                   │
│         - Zoomable time scale                                        │
│         - Draggable start/end block boundary bars                    │
│         - Quick IN/OUT setting buttons                               │
└──────────────────────────────────────────────────────────────────────┘
```

### B. Frame-Exact Video Canvas Renderer
Instead of loading a standard HTML5 `<video>` element (which cannot seek frame-accurately in major browsers due to keyframe constraints), we render frames on a `<canvas>`.
* **Frame Navigation:** JavaScript triggers `fetch("/api/video/{job_id}/frame/{frame_idx}")` and draws the returning binary JPEG buffer onto the canvas.
* **Canvas Bounding Box Overlay:** The user clicks and drags a selection box over the canvas. These normalized coordinates (`[y_start, x_start, y_end, x_end]`) are stored in `app.js` and automatically persistent.

### C. Keyboard Shortcuts (Hotkeys)
Shortcuts will be managed by a global event listener:
* `Z` / `X`: Step 1 frame backward / forward.
* `Shift + Z` / `Shift + X`: Step 10 frames backward / forward.
* `A`: Set Subtitle **IN** (records current frame index as `start_frame`).
* `S`: Set Subtitle **OUT** (records current frame index as `end_frame`).
* `D`: Trigger **OCR** on the selected region for the current frame.
* `Enter`: **Save & Commit** active block to list.
* `Space`: Play / Pause video (implemented as a slow playback loop rendering frames via requests).
* `Ctrl + T`: Translate current line via LibreTranslate.

---

## 4. API Specification

* **`GET /api/video/session/{job_id}`**
  * Initializes the `VideoDecoder` session for a specified video.
  * Returns: `{width, height, fps, total_frames, duration_sec}`.

* **`GET /api/video/{job_id}/frame/{frame_idx}`**
  * Decodes and streams the specific frame as a `image/jpeg` response.

* **`POST /api/ocr/process-frame`**
  * Payload: `{job_id, frame_idx, region: [y1, x1, y2, x2], config: {engine, lang, preprocessing}}`.
  * Action: Fetches the frame, crops it, checks cache, processes OCR if cache-miss, stores result in cache.
  * Returns: `{text, confidence, cached: true/false}`.

* **`POST /api/subtitle/save-job`**
  * Saves the current list of `SubtitleBlocks` to `output/{job_id}/subtitles.json`.

* **`GET /api/subtitle/export/{job_id}/{format}`**
  * Exports compiled blocks to `.srt`, `.vtt`, `.json`, or `.ass`.
