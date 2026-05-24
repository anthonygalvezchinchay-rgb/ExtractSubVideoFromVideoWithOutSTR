# Proposal: Human-Assisted Subtitle Authoring Refactor

## 1. Executive Summary & Goals
The objective of this refactor is to transition **SubtitleForge** from a fully automatic, resource-intensive "batch OCR streaming" pipeline into an interactive, **Human-Assisted Subtitle Authoring** tool (inspired by Aegisub and Subtitle Edit workflows). 

The current pipeline suffers from high CPU/GPU overhead, frame-drift timing issues, high false-positive rates on stylized text (anime fonts), and memory exhaustion on budget hardware. By shifting control to the user, we will achieve:
- **Zero-drift, frame-exact video navigation.**
- **Extreme efficiency:** OCR will run strictly *on-demand* on individual frames rather than scanning entire videos.
- **High precision:** Eliminating automated timing heuristics (SSIM-based change detection) in favor of user-defined IN/OUT timing, with optional automated assistance.
- **Aegisub-style fansub workflow:** Keyboard-centric editing, interactive canvas region selection, and instant OCR/translation helpers.

---

## 2. Transition Plan: Old vs. New Architecture

| Feature | Current Architecture (Batch Auto) | New Architecture (Human-Assisted) |
| :--- | :--- | :--- |
| **Pipeline Mode** | Single, rigid automatic pipeline (`processor.py`). | Dual Modes: `MANUAL_ASSIST` (Default) and `BATCH_AUTO` (Legacy). |
| **Video Decoding** | Complete streaming extraction to disk/memory (`frame_extractor.py`). | Persistent, random-access frame decoder (`PyAV` / OpenCV). |
| **Timing Detection** | Continuous SSIM calculation between all extracted crops. | Manual IN/OUT markers (Frame Index) set by the user; optional local SSIM assist. |
| **OCR Frequency** | OCR run on every detected text change across the entire video. | Strictly **On-Demand** via a single button or keyboard shortcut (`D`). |
| **Region of Interest** | Automated bounding box heuristic calculated per frame. | Persistent, user-defined bounding box drawn once and normalized. |
| **Resource Profile** | Constant high CPU/GPU/IO usage. Risk of system crashes. | Idle resources during seeking; sub-second CPU spike only during OCR. |

---

## 3. Impact on Modules & APIs

### Módulos a Eliminar o Archivar
- **`modules/frame_extractor.py`**: Fully replaced by the persistent, frame-exact decoder service.
- **`modules/change_detector.py`**: Removed from the default workflow; code archived/re-factored into `modules/auto_assist.py` for optional automatic timing helpers.

### Módulos a Refactorizar
- **`modules/ocr_engine.py`**:
  - Add native support for **Japanese/Anime Outlined Fonts** (adding specialized Japanese models for PaddleOCR/EasyOCR and optional vision-encoder-decoder plugins like `manga-ocr`).
  - Strict lazy initialization of backends until the first on-demand request is made.
- **`modules/preprocessor.py`**:
  - Expose independent quality filters (CLAHE, Otsu binarization, padding) so they can be applied interactively on the user-selected cropped region.
- **`server.py` & `job_manager.py`**:
  - Replace the streaming websocket progress tracker with a persistent session model.
  - Expose API endpoints for frame fetching: `/api/video/{job_id}/frame/{frame_idx}`.
  - Expose API endpoints for on-demand OCR: `/api/ocr/process-frame`.

---

## 4. Performance & Memory Impact
1. **CPU/GPU RAM:** Python memory usage will remain flat (under 200MB) during navigation. OCR models are initialized once and idle until invoked, respecting `OMP_NUM_THREADS=1` and GPU context allocations.
2. **Storage I/O:** Eliminates the writing of thousands of temporary JPG crops to `/temp`. All cropping and pre-processing occurs in-memory.
3. **Latency:** Frame rendering latency will be kept under 50ms for local files, enabling real-time seeking.
