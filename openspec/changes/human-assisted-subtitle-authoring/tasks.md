# Tasks: Human-Assisted Subtitle Authoring Refactor

Detailed checklist for implementing the Aegisub-style human-assisted authoring refactor.

---

## Phase 1: Core Backend Refactoring & Decoder Integration
- [x] Create `modules/video_decoder.py` with PyAV and OpenCV fallback for frame-exact navigation.
- [x] Implement PyAV packet decoding and seek-to-frame logic using PTS timestamps.
- [x] Create `modules/cache_manager.py` with MD5-based grayscale crop hashing and JSON persistence.
- [x] Modify `modules/ocr_engine.py` to add MangaOCR optional support and load models lazily on-demand.
- [x] Refactor `modules/preprocessor.py` to expose standalone image filter functions (CLAHE, Otsu, Padding) to be used directly on Numpy arrays.

---

## Phase 2: FastAPI Routing & Server Updates
- [x] Create the new REST API session endpoint `GET /api/video/session/{job_id}` in `server.py`.
- [x] Implement the frame-by-frame streaming endpoint `GET /api/video/{job_id}/frame/{frame_idx}` in `server.py` with proper HTTP caching/headers.
- [x] Implement the on-demand OCR processing endpoint `POST /api/ocr/process-frame` in `server.py`.
- [x] Implement subtitle list persistence endpoints `POST /api/subtitle/save-job` and `GET /api/subtitle/load-job`.
- [x] Update `job_manager.py` to maintain active persistent decoders for loaded jobs and automatically clean up resources on expiry.

---

## Phase 3: Interactive Fansub Frontend UI
- [x] Redesign `frontend/index.html` structure with the new three-pane layout (Video Player on left, Editor/Blocks on right, Timeline on bottom).
- [x] Update `frontend/styles.css` to add dark-mode grid styling, glassmorphism containers, and custom properties.
- [x] Implement canvas drawing logic in `frontend/app.js` to draw fetched frame buffers and keep rendering latency low.
- [x] Implement canvas-based bounding box selection drawing (mouse drag to select region) and normalize coordinates.
- [x] Implement the keyboard shortcuts event listener (Z/X for frames, A/S for timing, D for OCR, Enter for saving).

---

## Phase 4: Subtitle Timeline & Exporter
- [x] Build an interactive, draggable subtitle timeline component at the bottom of the interface.
- [x] Add support for dragging start/end borders of blocks on the timeline to refine timings.
- [x] Update `modules/srt_writer.py` to support exporting subtitle blocks to standard Advanced SubStation Alpha (`.ass` / `.ssa`) style sheets.
- [x] Verify translation support integration using local LibreTranslate service on-demand (`Ctrl+T` shortcut).

---

## Phase 5: Testing, Polish & Verification
- [x] Verify frame-accurate seek consistency with video players like mpv/Aegisub.
- [x] Test Japanese/Anime subtitle OCR using PaddleOCR JP and verify outline preprocessing filters.
- [x] Test the cache hits and VRAM/RAM consumption during a simulated subtitle extraction session.
