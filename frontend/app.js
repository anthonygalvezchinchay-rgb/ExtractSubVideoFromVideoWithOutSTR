// app.js — SubtitleForge Interactive Fansub Studio Client
const API = window.location.origin + '/api';

// ─── Application State ──────────────────────────────────────────────────────
const state = {
    currentSection: 'upload', // 'upload', 'workspace'
    jobId: null,
    video: null,           // { fps, total_frames, width, height, duration_sec }
    currentFrame: 0,
    isPlaying: false,
    playInterval: null,

    // Active block being drafted
    activeBlock: {
        startFrame: null,
        endFrame: null,
        text: '',
        translation: '',
    },

    // Subtitle Blocks list
    blocks: [],            // list of blocks in memory
    selectedBlockIndex: null,

    // Region configuration (normalized bounding box: [y1, x1, y2, x2])
    region: [0.72, 0.05, 0.98, 0.95], // default to bottom region

    // OCR configurations
    ocrConfig: {
        engine: 'auto',
        lang: 'ja',
        preprocessing: {
            upscale: true,
            denoise: true,
            sharpen: true,
            contrast: true,
            binarize: false,
            padding: true
        }
    }
};

// ─── Canvas Selector State ──────────────────────────────────────────────────
let isSelecting = false;
let startX = 0, startY = 0;
let currentX = 0, currentY = 0;
let currentImgBlobUrl = null;

// ─── DOM References ──────────────────────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ─── Initialisation ──────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    setupUpload();
    setupWorkspace();
    setupCanvasSelector();
    setupHotkeys();
    checkHealth();
});

// ─── API Health & Configurations ─────────────────────────────────────────────
async function checkHealth() {
    try {
        const resp = await fetch(`${API}/health`);
        const data = await resp.json();

        // Update badges
        const ocrBadge = $('#badge-ocr');
        ocrBadge.querySelector('.badge-label').textContent = (data.ocr_engines || []).join(', ') || 'No OCR';
        ocrBadge.className = 'badge ' + (data.ocr_engines?.length ? 'badge-active' : 'badge-neutral');

        const transBadge = $('#badge-translate');
        transBadge.querySelector('.badge-label').textContent = data.libretranslate_available ? 'Traducción ✓' : 'Sin traducción';
        transBadge.className = 'badge ' + (data.libretranslate_available ? 'badge-active' : 'badge-neutral');

        if (data.libretranslate_available) {
            state.ocrConfig.lang = 'ja'; // Default to Japanese OCR
        }
    } catch (e) {
        console.warn('Health check failed:', e);
    }
}

// ─── Upload Handler ──────────────────────────────────────────────────────────
function setupUpload() {
    const zone = $('#upload-zone');
    const fileInput = $('#file-input');

    zone.addEventListener('click', () => fileInput.click());
    zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('dragover'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
    zone.addEventListener('drop', (e) => {
        e.preventDefault();
        zone.classList.remove('dragover');
        if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
    });
    fileInput.addEventListener('change', () => {
        if (fileInput.files.length) handleFile(fileInput.files[0]);
    });
}

async function handleFile(file) {
    $('#upload-progress').classList.remove('hidden');
    $('#upload-filename').textContent = file.name;
    $('#upload-bar').style.width = '0%';
    $('#upload-percent').textContent = '0%';

    try {
        const formData = new FormData();
        formData.append('file', file);

        const xhr = new XMLHttpRequest();
        xhr.open('POST', `${API}/upload`);

        xhr.upload.onprogress = (e) => {
            if (e.lengthComputable) {
                const pct = Math.round((e.loaded / e.total) * 100);
                $('#upload-bar').style.width = pct + '%';
                $('#upload-percent').textContent = pct + '%';
            }
        };

        const response = await new Promise((resolve, reject) => {
            xhr.onload = () => {
                if (xhr.status === 200) resolve(JSON.parse(xhr.responseText));
                else reject(new Error(xhr.responseText));
            };
            xhr.onerror = () => reject(new Error('Subida fallida'));
            xhr.send(formData);
        });

        state.jobId = response.job_id;
        await startInteractiveSession(response.job_id);
    } catch (e) {
        alert('Error subiendo video: ' + e.message);
        $('#upload-progress').classList.add('hidden');
    }
}

// ─── Workspace Sessions ──────────────────────────────────────────────────────
async function startInteractiveSession(jobId) {
    try {
        const resp = await fetch(`${API}/video/session/${jobId}`);
        if (!resp.ok) throw new Error('No se pudo iniciar la sesión de video');
        const data = await resp.json();

        state.video = data.video;
        state.currentFrame = 0;
        state.blocks = [];
        state.selectedBlockIndex = null;

        // Load existing work if any
        try {
            const savedResp = await fetch(`${API}/subtitle/load-job/${jobId}`);
            if (savedResp.ok) {
                const savedData = await savedResp.json();
                if (savedData.subtitles) state.blocks = savedData.subtitles;
                if (savedData.region) state.region = savedData.region;
            }
        } catch (e) {
            console.log('No saved subtitles found.');
        }

        // Setup UI limits
        $('#total-frames').textContent = state.video.total_frames;
        renderActiveBlockTiming();
        updateSubtitleList();
        renderTimeline();

        // Switch screen
        $('#section-upload').classList.add('hidden');
        $('#section-workspace').classList.remove('hidden');
        state.currentSection = 'workspace';

        // Load first frame
        await fetchAndDrawFrame(0);
    } catch (e) {
        alert('Error cargando el estudio interactivo: ' + e.message);
    }
}

// ─── Video Rendering & Playback ──────────────────────────────────────────────
async function fetchAndDrawFrame(frameIdx) {
    if (frameIdx < 0 || frameIdx >= state.video.total_frames) return;
    state.currentFrame = frameIdx;

    try {
        const response = await fetch(`${API}/video/${state.jobId}/frame/${frameIdx}`);
        if (!response.ok) return;

        const blob = await response.blob();
        if (currentImgBlobUrl) {
            URL.revokeObjectURL(currentImgBlobUrl);
        }
        currentImgBlobUrl = URL.createObjectURL(blob);

        const img = new Image();
        img.onload = () => {
            drawWorkspaceCanvas(img);
        };
        img.src = currentImgBlobUrl;

        // Parse headers
        const ts = parseFloat(response.headers.get('X-Timestamp') || '0');
        $('#current-frame').textContent = frameIdx;
        $('#current-time').textContent = formatTimestamp(ts);

        // Auto select active subtitle segment on timeline
        highlightTimelineFrame();
    } catch (e) {
        console.error('Frame rendering error:', e);
    }
}

function drawWorkspaceCanvas(img) {
    const canvas = $('#video-canvas');
    const ctx = canvas.getContext('2d');

    // Keep aspect ratio intact
    canvas.width = canvas.clientWidth;
    canvas.height = canvas.clientHeight;

    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

    // Draw the active bounding box region selection
    if (state.region) {
        const [y1, x1, y2, x2] = state.region;
        ctx.strokeStyle = '#8b5cf6';
        ctx.lineWidth = 2;
        ctx.strokeRect(
            x1 * canvas.width,
            y1 * canvas.height,
            (x2 - x1) * canvas.width,
            (y2 - y1) * canvas.height
        );
        // Semi-transparent overlay outside the region
        ctx.fillStyle = 'rgba(0, 0, 0, 0.4)';
        ctx.fillRect(0, 0, canvas.width, y1 * canvas.height); // Top
        ctx.fillRect(0, y2 * canvas.height, canvas.width, (1 - y2) * canvas.height); // Bottom
        ctx.fillRect(0, y1 * canvas.height, x1 * canvas.width, (y2 - y1) * canvas.height); // Left
        ctx.fillRect(x2 * canvas.width, y1 * canvas.height, (1 - x2) * canvas.width, (y2 - y1) * canvas.height); // Right
    }

    // Draw active drawing box
    if (isSelecting) {
        ctx.strokeStyle = '#3b82f6';
        ctx.lineWidth = 2;
        ctx.setLineDash([6, 3]);
        ctx.strokeRect(startX, startY, currentX - startX, currentY - startY);
        ctx.setLineDash([]);
    }
}

function togglePlayback() {
    if (state.isPlaying) {
        clearInterval(state.playInterval);
        state.isPlaying = false;
        $('#btn-play').textContent = '▶';
    } else {
        state.isPlaying = true;
        $('#btn-play').textContent = '⏸';
        const msPerFrame = 1000 / state.video.fps;
        state.playInterval = setInterval(async () => {
            if (state.currentFrame + 1 >= state.video.total_frames) {
                togglePlayback(); // Stop at EOF
                return;
            }
            await fetchAndDrawFrame(state.currentFrame + 1);
        }, msPerFrame);
    }
}

// ─── Canvas Mouse Region Selectors ──────────────────────────────────────────
function setupCanvasSelector() {
    const canvas = $('#video-canvas');

    canvas.addEventListener('mousedown', (e) => {
        const rect = canvas.getBoundingClientRect();
        startX = e.clientX - rect.left;
        startY = e.clientY - rect.top;
        isSelecting = true;
    });

    canvas.addEventListener('mousemove', (e) => {
        if (!isSelecting) return;
        const rect = canvas.getBoundingClientRect();
        currentX = e.clientX - rect.left;
        currentY = e.clientY - rect.top;
        redrawCanvasOnly();
    });

    canvas.addEventListener('mouseup', (e) => {
        if (!isSelecting) return;
        isSelecting = false;
        const rect = canvas.getBoundingClientRect();
        const endX = e.clientX - rect.left;
        const endY = e.clientY - rect.top;

        // Calculate and normalize coordinates
        const x1 = Math.min(startX, endX) / canvas.width;
        const x2 = Math.max(startX, endX) / canvas.width;
        const y1 = Math.min(startY, endY) / canvas.height;
        const y2 = Math.max(startY, endY) / canvas.height;

        // Only commit if selection is valid size
        if ((x2 - x1) > 0.02 && (y2 - y1) > 0.02) {
            state.region = [y1, x1, y2, x2];
            saveSession();
        }
        redrawCanvasOnly();
    });
}

function redrawCanvasOnly() {
    const img = new Image();
    img.onload = () => drawWorkspaceCanvas(img);
    img.src = currentImgBlobUrl;
}

// ─── Workspace Interactive logic ────────────────────────────────────────────
function setupWorkspace() {
    // Navigation
    $('#btn-prev').addEventListener('click', () => fetchAndDrawFrame(state.currentFrame - 1));
    $('#btn-next').addEventListener('click', () => fetchAndDrawFrame(state.currentFrame + 1));
    $('#btn-prev-10').addEventListener('click', () => fetchAndDrawFrame(state.currentFrame - 10));
    $('#btn-next-10').addEventListener('click', () => fetchAndDrawFrame(state.currentFrame + 10));

    // Playback
    $('#btn-play').addEventListener('click', togglePlayback);

    // Timings
    $('#btn-set-in').addEventListener('click', () => {
        state.activeBlock.startFrame = state.currentFrame;
        renderActiveBlockTiming();
    });
    $('#btn-set-out').addEventListener('click', () => {
        state.activeBlock.endFrame = state.currentFrame;
        renderActiveBlockTiming();
    });

    // OCR
    $('#btn-ocr').addEventListener('click', triggerOCR);

    // Preview preprocessed image that MangaOCR receives
    $('#btn-preview-crop').addEventListener('click', async () => {
        const payload = {
            job_id: state.jobId,
            frame_idx: state.currentFrame,
            region: state.region
        };
        try {
            const resp = await fetch(`${API}/ocr/preview-crop`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (!resp.ok) { alert('Error obteniendo preview. ¿Hay un frame cargado?'); return; }
            const blob = await resp.blob();
            const url = URL.createObjectURL(blob);
            window.open(url, '_blank');
        } catch (e) {
            alert('Error: ' + e.message);
        }
    });

    // Commit Subtitle
    $('#btn-save-sub').addEventListener('click', commitSubtitleBlock);

    // Save session
    $('#btn-save-session').addEventListener('click', saveSession);

    // Next Subtitle
    $('#btn-next-sub').addEventListener('click', () => {
        state.activeBlock = {
            startFrame: null,
            endFrame: null,
            text: '',
            translation: '',
        };
        $('#active-text').value = '';
        $('#active-translation').value = '';
        $('#ocr-confidence').textContent = '—';
        $('#ocr-cached').classList.add('hidden');
        renderActiveBlockTiming();
    });

    // Modals
    $('#btn-shortcuts').addEventListener('click', () => $('#shortcuts-modal').classList.remove('hidden'));
    $('#btn-close-modal').addEventListener('click', () => $('#shortcuts-modal').classList.add('hidden'));

    // Text inputs
    $('#active-text').addEventListener('input', (e) => state.activeBlock.text = e.target.value);
    $('#active-translation').addEventListener('input', (e) => state.activeBlock.translation = e.target.value);

    // Export Row
    $$('.btn-export').forEach(btn => {
        btn.addEventListener('click', () => {
            const format = btn.dataset.format;
            window.open(`${API}/subtitle/export/${state.jobId}/${format}`, '_blank');
        });
    });
}

function renderActiveBlockTiming() {
    const formatTimeVal = (frameIdx) => {
        if (frameIdx === null || frameIdx === undefined) return '—';
        const sec = frameIdx / state.video.fps;
        return `${formatTimestamp(sec)} (f:${frameIdx})`;
    };

    $('#active-in').textContent = formatTimeVal(state.activeBlock.startFrame);
    $('#active-out').textContent = formatTimeVal(state.activeBlock.endFrame);
}

async function triggerOCR() {
    $('#btn-ocr').disabled = true;
    $('#btn-ocr').textContent = '🔍 Buscando...';

    // Update config from UI inputs
    state.ocrConfig.engine = $('#sel-ocr-engine').value;
    state.ocrConfig.preprocessing = {
        upscale: $('#chk-upscale').checked,
        denoise: $('#chk-denoise').checked,
        contrast: $('#chk-contrast').checked,
        sharpen: $('#chk-sharpen').checked,
        binarize: $('#chk-binarize').checked,
        padding: $('#chk-padding').checked
    };

    try {
        const payload = {
            job_id: state.jobId,
            frame_idx: state.currentFrame,
            region: state.region,
            config: state.ocrConfig
        };

        const resp = await fetch(`${API}/ocr/process-frame`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!resp.ok) throw new Error('OCR API Error');
        const data = await resp.json();

        // Populate fields
        state.activeBlock.text = data.text;
        $('#active-text').value = data.text;

        // Confidence & caching labels
        $('#ocr-confidence').textContent = data.confidence ? `Confianza: ${Math.round(data.confidence * 100)}%` : 'Sin texto';
        const cachedBadge = $('#ocr-cached');
        if (data.cached) {
            cachedBadge.classList.remove('hidden');
        } else {
            cachedBadge.classList.add('hidden');
        }

        // Trigger Auto Translate if LibreTranslate is active and language is Japanese
        if (data.text.trim() && $('#badge-translate').classList.contains('badge-active')) {
            await triggerTranslation();
        }
    } catch (e) {
        console.error('OCR Error:', e);
    } finally {
        $('#btn-ocr').disabled = false;
        $('#btn-ocr').textContent = 'D 🔍 OCR';
    }
}

async function triggerTranslation() {
    try {
        const resp = await fetch(`${API}/translate-line`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                text: state.activeBlock.text,
                source: 'ja',
                target: 'es'
            })
        });
        if (resp.ok) {
            const data = await resp.json();
            state.activeBlock.translation = data.translated;
            $('#active-translation').value = data.translated;
        }
    } catch (e) {
        console.warn('Translation failed:', e);
    }
}

// ─── Subtitle Commit Logic ──────────────────────────────────────────────────
function commitSubtitleBlock() {
    const { startFrame, endFrame, text, translation } = state.activeBlock;

    if (startFrame === null || endFrame === null) {
        alert('Debes definir los marcos IN y OUT antes de guardar.');
        return;
    }
    if (startFrame > endFrame) {
        alert('El marco IN debe ser anterior al marco OUT.');
        return;
    }

    const block = {
        index: state.blocks.length + 1,
        start_frame: startFrame,
        end_frame: endFrame,
        start_time: startFrame / state.video.fps,
        end_time: endFrame / state.video.fps,
        text_original: text,
        text_translated: translation,
        edited_by_user: true
    };

    // Insert block sorted by frame index
    state.blocks.push(block);
    state.blocks.sort((a, b) => a.start_frame - b.start_frame);

    // Re-index all blocks sequentially
    state.blocks.forEach((b, idx) => b.index = idx + 1);

    // Reset active draft values
    state.activeBlock = {
        startFrame: null,
        endFrame: null,
        text: '',
        translation: '',
    };
    $('#active-text').value = '';
    $('#active-translation').value = '';
    $('#ocr-confidence').textContent = '—';
    $('#ocr-cached').classList.add('hidden');

    renderActiveBlockTiming();
    updateSubtitleList();
    renderTimeline();
    saveSession();
}

function updateSubtitleList() {
    const container = $('#subtitle-list');
    container.innerHTML = '';

    if (state.blocks.length === 0) {
        container.innerHTML = `<p class="empty-message">Sin subtítulos aún. Usa <kbd>A</kbd>/<kbd>S</kbd> para marcar tiempos y <kbd>D</kbd> para OCR.</p>`;
        $('#subtitle-count').textContent = '0';
        return;
    }

    $('#subtitle-count').textContent = state.blocks.length;

    state.blocks.forEach((block, idx) => {
        const item = document.createElement('div');
        item.className = 'sub-item-card';
        if (state.selectedBlockIndex === idx) {
            item.classList.add('active');
        }

        const startT = formatTimestamp(block.start_time);
        const endT = formatTimestamp(block.end_time);

        item.innerHTML = `
            <div class="sub-item-top">
                <span class="sub-item-index">#${block.index}</span>
                <span>${startT} ── ${endT}</span>
            </div>
            <div class="sub-item-text">${escapeHtml(block.text_original || '[Vacío]')}</div>
            ${block.text_translated ? `<div class="sub-item-trans">${escapeHtml(block.text_translated)}</div>` : ''}
        `;

        item.addEventListener('click', () => {
            state.selectedBlockIndex = idx;
            // Go to start frame
            fetchAndDrawFrame(block.start_frame);
            // Put into active fields for edit reference
            state.activeBlock = {
                startFrame: block.start_frame,
                endFrame: block.end_frame,
                text: block.text_original,
                translation: block.text_translated
            };
            $('#active-text').value = block.text_original;
            $('#active-translation').value = block.text_translated;
            renderActiveBlockTiming();
            updateSubtitleList();
        });

        container.appendChild(item);
    });
}

// ─── Save Session to Backend ────────────────────────────────────────────────
async function saveSession() {
    if (!state.jobId) return;
    try {
        await fetch(`${API}/subtitle/save-job`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                job_id: state.jobId,
                blocks: state.blocks,
                region: state.region
            })
        });
    } catch (e) {
        console.warn('Failed to save subtitle session:', e);
    }
}

// ─── Timeline Rendering (Vanilla Canvas) ────────────────────────────────────
function renderTimeline() {
    const canvas = $('#timeline-canvas');
    if (!canvas || !state.video) return;

    const ctx = canvas.getContext('2d');
    canvas.width = canvas.clientWidth;
    canvas.height = canvas.clientHeight;

    ctx.fillStyle = '#0f0f16';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // Draw horizontal ticks/rulers
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
    ctx.lineWidth = 1;
    const ticksCount = 20;
    const tickSpacing = canvas.width / ticksCount;
    for (let i = 0; i <= ticksCount; i++) {
        const x = i * tickSpacing;
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, canvas.height);
        ctx.stroke();
    }

    // Draw subtitle blocks on timeline
    const totalFrames = state.video.total_frames;
    state.blocks.forEach(block => {
        const x1 = (block.start_frame / totalFrames) * canvas.width;
        const x2 = (block.end_frame / totalFrames) * canvas.width;
        const width = Math.max(2, x2 - x1);

        ctx.fillStyle = 'rgba(139, 92, 246, 0.3)';
        ctx.strokeStyle = '#8b5cf6';
        ctx.lineWidth = 1;
        ctx.fillRect(x1, 10, width, canvas.height - 20);
        ctx.strokeRect(x1, 10, width, canvas.height - 20);

        // Text index overlay
        ctx.fillStyle = '#f8fafc';
        ctx.font = '9px monospace';
        ctx.fillText(`#${block.index}`, x1 + 4, 25);
    });

    // Draw playhead (current frame)
    const playheadX = (state.currentFrame / totalFrames) * canvas.width;
    ctx.strokeStyle = '#ef4444';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(playheadX, 0);
    ctx.lineTo(playheadX, canvas.height);
    ctx.stroke();

    // Red circle at top of playhead
    ctx.fillStyle = '#ef4444';
    ctx.beginPath();
    ctx.arc(playheadX, 3, 3, 0, 2 * Math.PI);
    ctx.fill();

    $('#timeline-info').textContent = `${state.blocks.length} bloques`;

    // Click handler for seeking
    canvas.onclick = (e) => {
        const rect = canvas.getBoundingClientRect();
        const clickX = e.clientX - rect.left;
        const frameIdx = Math.round((clickX / canvas.width) * totalFrames);
        fetchAndDrawFrame(frameIdx);
    };
}

function highlightTimelineFrame() {
    renderTimeline();
}

// ─── Keyboard Hotkeys ────────────────────────────────────────────────────────
function setupHotkeys() {
    window.addEventListener('keydown', async (e) => {
        // Exclude inputs, selects & textarea so text inputting still works normally
        const tag = e.target.tagName.toLowerCase();
        if (tag === 'input' || tag === 'textarea' || tag === 'select') {
            // Exceptions: Ctrl+S or Escape or Ctrl+T in inputs
            if (e.key.toLowerCase() === 's' && e.ctrlKey) {
                e.preventDefault();
                await saveSession();
                alert('¡Sesión guardada con éxito!');
            }
            if (e.key === 'Escape') {
                $('#shortcuts-modal').classList.add('hidden');
            }
            if (e.key.toLowerCase() === 't' && e.ctrlKey) {
                e.preventDefault();
                await triggerTranslation();
            }
            return;
        }

        const key = e.key.toLowerCase();

        switch (e.key) {
            case 'z':
            case 'Z':
                e.preventDefault();
                if (e.shiftKey) {
                    fetchAndDrawFrame(state.currentFrame - 10);
                } else {
                    fetchAndDrawFrame(state.currentFrame - 1);
                }
                break;
            case 'x':
            case 'X':
                e.preventDefault();
                if (e.shiftKey) {
                    fetchAndDrawFrame(state.currentFrame + 10);
                } else {
                    fetchAndDrawFrame(state.currentFrame + 1);
                }
                break;
            case 'a':
            case 'A':
                e.preventDefault();
                state.activeBlock.startFrame = state.currentFrame;
                renderActiveBlockTiming();
                break;
            case 's':
            case 'S':
                if (e.ctrlKey) {
                    e.preventDefault();
                    await saveSession();
                    alert('¡Sesión guardada con éxito!');
                } else {
                    e.preventDefault();
                    state.activeBlock.endFrame = state.currentFrame;
                    renderActiveBlockTiming();
                }
                break;
            case 'd':
            case 'D':
                e.preventDefault();
                await triggerOCR();
                break;
            case 'Enter':
                e.preventDefault();
                commitSubtitleBlock();
                break;
            case ' ':
                e.preventDefault();
                togglePlayback();
                break;
            case 'Escape':
                $('#shortcuts-modal').classList.add('hidden');
                break;
            default:
                if (key === 't' && e.ctrlKey) {
                    e.preventDefault();
                    await triggerTranslation();
                }
                break;
        }
    });
}

// ─── Helper utilities ────────────────────────────────────────────────────────
function formatTimestamp(seconds) {
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    const ms = Math.floor((seconds % 1) * 1000);
    return `${hours.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}.${ms.toString().padStart(3, '0')}`;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}
