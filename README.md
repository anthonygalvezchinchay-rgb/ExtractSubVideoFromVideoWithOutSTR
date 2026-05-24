# SubtitleForge — Interactive Subtitle Authoring Studio

An interactive, human-assisted subtitle extraction and authoring tool optimized for anime and hardcoded subtitles.

![SubtitleForge Studio UI](https://raw.githubusercontent.com/anthonygalvezchinchay-rgb/ExtractSubVideoFromVideoWithOutSTR/main/frontend/screenshot.png) *(Placeholder or screenshot link)*

## Key Features

- 🎯 **Frame-Exact Video Seeking**: Built with `PyAV` (FFmpeg bindings) to navigate frame-by-frame with zero timestamp drift.
- 🔍 **On-Demand OCR**: Powered by **MangaOCR** (Vision Transformer for Japanese) and **PaddleOCR** / **EasyOCR** for precise extraction of hardcoded anime subtitles.
- ⚡ **Lazy Loading & Smart Caching**: Models are loaded only when requested. Grayscale crops are hashed using MD5 to skip processing identical lines.
- 🎹 **Keyboard-Centric Interface**: Fully interactive canvas player with pro fansubbing hotkeys:
  - `Z` / `X`: Move backward/forward by 1 frame.
  - `A` / `S`: Set subtitle Start / End times.
  - `D`: Trigger OCR on the selected bounding box.
  - `Enter`: Save current subtitle to the list.
  - `Space`: Play/Pause video.
- 💾 **Advanced Export Formats**: Subtitle generation in `.srt`, `.vtt`, `.json`, and styled Advanced SubStation Alpha (`.ass` / `.ssa`).

---

## Installation

### Prerequisites
- Python 3.12 (highly recommended due to PaddleOCR compatibility)
- FFmpeg installed on your system

### Quick Start
1. Clone this repository:
   ```bash
   git clone https://github.com/anthonygalvezchinchay-rgb/ExtractSubVideoFromVideoWithOutSTR.git
   cd ExtractSubVideoFromVideoWithOutSTR
   ```

2. Run the setup script to initialize your virtual environment and install all packages:
   ```bash
   chmod +x setup.sh
   ./setup.sh
   ```

3. Activate the environment and run the server:
   ```bash
   source venv/bin/activate
   python server.py
   ```

4. Open your browser and navigate to:
   ```
   http://localhost:8000
   ```

---

## Tech Stack
- **Backend**: FastAPI (Python), PyAV (FFmpeg), MangaOCR, PaddleOCR, EasyOCR.
- **Frontend**: Vanilla ES6+ JS, CSS3 (Glassmorphism Dark Theme), HTML5 Canvas.
