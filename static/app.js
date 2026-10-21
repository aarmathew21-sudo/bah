// ==========================================================================
// PPT & PDF STUDY AI - COMPLETE CLIENT APPLICATION
// Gamified active recall, Spaced Repetition (SM-2), Boss Battle & AI Tutor
// ==========================================================================

// Global State
let presentationData = null;
let currentFlashcardIndex = 0;
let flashcardsList = [];
let quizList = [];
let chatHistory = [];
let currentDocFilter = 'ALL';
let tldrModeActive = false;
let selectedTeacherPersona = 'socratic';
let quizMasterMode = 'classic'; // 'classic' or 'boss'

// Session Tracking (Client telemetry synced with server-side XP)
const sessionTracker = {
    startTime: Date.now(),
    xpEarned: 0,
    cardsReviewed: 0,
    quizAttempts: 0,
    quizCorrect: 0
};

// ==========================================================================
// 1. SOUND SYSTEM (Pure Web Audio API - Zero External Assets)
// ==========================================================================
class SoundFX {
    constructor() {
        this.ctx = null;
        this.enabled = localStorage.getItem('sound_enabled') === 'true';
    }

    init() {
        const toggleBtn = document.getElementById('soundToggleBtn');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', () => this.toggle());
            this.updateButtonUI();
        }
    }

    getAudioContext() {
        if (!this.ctx && (window.AudioContext || window.webkitAudioContext)) {
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            this.ctx = new AudioCtx();
        }
        if (this.ctx && this.ctx.state === 'suspended') {
            this.ctx.resume();
        }
        return this.ctx;
    }

    toggle() {
        this.enabled = !this.enabled;
        localStorage.setItem('sound_enabled', this.enabled ? 'true' : 'false');
        this.updateButtonUI();
        if (this.enabled) {
            this.correct(); // Play a cheerful preview chime
        }
    }

    updateButtonUI() {
        const icon = document.getElementById('soundIcon');
        const text = document.getElementById('soundText');
        const toggleBtn = document.getElementById('soundToggleBtn');
        if (!icon || !text || !toggleBtn) return;

        if (this.enabled) {
            icon.className = 'fa-solid fa-volume-high';
            text.textContent = 'Sound: ON';
            toggleBtn.classList.add('active');
        } else {
            icon.className = 'fa-solid fa-volume-xmark';
            text.textContent = 'Sound: OFF';
            toggleBtn.classList.remove('active');
        }
    }

    playTone(freq, type = 'sine', duration = 0.15, gainStart = 0.12, gainEnd = 0.001) {
        if (!this.enabled) return;
        try {
            const ctx = this.getAudioContext();
            if (!ctx) return;
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();

            osc.type = type;
            osc.frequency.setValueAtTime(freq, ctx.currentTime);

            gain.gain.setValueAtTime(gainStart, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(gainEnd, ctx.currentTime + duration);

            osc.connect(gain);
            gain.connect(ctx.destination);

            osc.start();
            osc.stop(ctx.currentTime + duration);
        } catch (e) {
            console.warn('Audio playback error', e);
        }
    }

    flip() {
        // Subtle wooden/paper flip sound
        this.playTone(320, 'triangle', 0.08, 0.08, 0.001);
    }

    correct() {
        // Bright upward major chord arpeggio
        if (!this.enabled) return;
        try {
            const ctx = this.getAudioContext();
            if (!ctx) return;
            const now = ctx.currentTime;
            [523.25, 659.25, 783.99].forEach((freq, idx) => {
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.type = 'sine';
                osc.frequency.setValueAtTime(freq, now + idx * 0.08);
                gain.gain.setValueAtTime(0.12, now + idx * 0.08);
                gain.gain.exponentialRampToValueAtTime(0.001, now + idx * 0.08 + 0.25);
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.start(now + idx * 0.08);
                osc.stop(now + idx * 0.08 + 0.25);
            });
        } catch (e) {}
    }

    again() {
        // Soft encouraging low tone (never harsh or punishing)
        this.playTone(220, 'sine', 0.2, 0.08, 0.001);
    }

    combo() {
        // High double-ping for combos
        this.playTone(880, 'sine', 0.1, 0.15, 0.001);
        setTimeout(() => this.playTone(1174, 'sine', 0.15, 0.15, 0.001), 70);
    }

    fanfare() {
        // Triumphant level-up / deck complete celebration
        if (!this.enabled) return;
        try {
            const ctx = this.getAudioContext();
            if (!ctx) return;
            const now = ctx.currentTime;
            [523.25, 659.25, 783.99, 1046.50].forEach((freq, idx) => {
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.type = 'triangle';
                osc.frequency.setValueAtTime(freq, now + idx * 0.1);
                gain.gain.setValueAtTime(0.15, now + idx * 0.1);
                gain.gain.exponentialRampToValueAtTime(0.001, now + idx * 0.1 + 0.35);
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.start(now + idx * 0.1);
                osc.stop(now + idx * 0.1 + 0.35);
            });
        } catch (e) {}
    }

    bossHit() {
        // Punchy downward pitch drop for boss strikes
        if (!this.enabled) return;
        try {
            const ctx = this.getAudioContext();
            if (!ctx) return;
            const now = ctx.currentTime;
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = 'sawtooth';
            osc.frequency.setValueAtTime(260, now);
            osc.frequency.exponentialRampToValueAtTime(70, now + 0.2);
            gain.gain.setValueAtTime(0.14, now);
            gain.gain.exponentialRampToValueAtTime(0.001, now + 0.2);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start(now);
            osc.stop(now + 0.2);
        } catch (e) {}
    }
}

const sounds = new SoundFX();

// ==========================================================================
// 2. LIFECYCLE & INITIALIZATION
// ==========================================================================
document.addEventListener('DOMContentLoaded', () => {
    sounds.init();
    initApiKey();
    initFileUpload();
    initExportText();
    initSearch();
    initTabs();
    initChat();
    initMasteryViewSwitch();
    initSessionFinish();
    checkCurrentSession();
});

function showError(msg) {
    const banner = document.getElementById('errorBanner');
    const text = document.getElementById('errorMessage');
    if (banner && text) {
        text.textContent = msg;
        banner.classList.remove('hidden');
    }
}

function hideError() {
    const banner = document.getElementById('errorBanner');
    if (banner) {
        banner.classList.add('hidden');
    }
}

// Text-To-Speech (TTS Read Aloud)
function speakText(text) {
    if (!('speechSynthesis' in window)) {
        alert('Text-to-speech is not supported in your browser.');
        return;
    }
    window.speechSynthesis.cancel();
    const cleanText = text
        .replace(/[*#_`~]/g, '')
        .replace(/📌|👨‍ish|💡|🧠|👋|📌/g, '')
        .trim();

    const utterance = new SpeechSynthesisUtterance(cleanText);
    utterance.rate = 1.0;
    utterance.pitch = 1.0;
    window.speechSynthesis.speak(utterance);
}

function stopSpeech() {
    if ('speechSynthesis' in window) {
        window.speechSynthesis.cancel();
    }
}

function readAloudStudyGuide() {
    const container = document.getElementById('summaryContainer');
    if (container) {
        speakText(container.textContent);
    }
}

// Anki CSV Export Handler
function exportAnkiCSV() {
    if (!flashcardsList || flashcardsList.length === 0) {
        alert('Please generate flashcards first before exporting to Anki.');
        return;
    }

    let csvContent = "Front,Back,Category\n";
    flashcardsList.forEach(card => {
        const front = `"${(card.front || '').replace(/"/g, '""')}"`;
        const back = `"${(card.back || '').replace(/"/g, '""')}"`;
        const cat = `"${(card.category || '').replace(/"/g, '""')}"`;
        csvContent += `${front},${back},${cat}\n`;
    });

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', `Anki_Flashcards_${presentationData ? presentationData.filename : 'document'}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// ==========================================================================
// 3. SESSION RESTORATION & "TODAY'S MISSION"
// ==========================================================================
async function checkCurrentSession() {
    try {
        const res = await fetch('/api/current');
        const data = await res.json();
        if (data.loaded) {
            presentationData = data;
            updateWorkspaceHeader(data);
            renderDocFilterBar(data.documents, data.filenames);
            renderSlides(data.slides);
            updateChatSuggestions(data.slides);

            document.getElementById('uploadSection').classList.add('hidden');
            document.getElementById('workspaceSection').classList.remove('hidden');

            await loadTodaysMission();
            await loadMasteryMap();
        }
    } catch (err) {
        console.log('Session check:', err.message);
    }
}

async function loadTodaysMission() {
    try {
        const [progRes, dueRes, masteryRes] = await Promise.all([
            fetch('/api/progress'),
            fetch(`/api/study/flashcards/due${getApiKey() ? `?api_key=${encodeURIComponent(getApiKey())}` : ''}`),
            fetch('/api/study/mastery')
        ]);

        const prog = progRes.ok ? await progRes.json() : null;
        const due = dueRes.ok ? await dueRes.json() : null;
        const mastery = masteryRes.ok ? await masteryRes.json() : null;

        if (prog) {
            const streakDaysEl = document.getElementById('missionStreakDays');
            if (streakDaysEl) streakDaysEl.textContent = prog.streak_days || 1;

            const levelBadge = document.getElementById('missionLevelBadge');
            if (levelBadge) {
                const title = prog.level_title || 'Novice';
                const icon = prog.level >= 3 ? '🧙' : (prog.level === 2 ? '📜' : '🌱');
                levelBadge.textContent = `${icon} ${title}`;
            }

            const xpBar = document.getElementById('missionXpBarFill');
            if (xpBar) {
                const pct = Math.min(100, Math.max(0, prog.progress_percent || 0));
                xpBar.style.width = `${pct}%`;
            }

            const xpText = document.getElementById('missionXpText');
            if (xpText) {
                xpText.textContent = `${prog.xp || 0} XP (Rank ${prog.level || 1})`;
            }
        }

        const dueCount = (due && due.total_due !== undefined) ? due.total_due : 0;
        const weakSpot = (mastery && mastery.weak_spots && mastery.weak_spots.length > 0)
            ? mastery.weak_spots[0]
            : null;

        const missionTitle = document.getElementById('missionTitle');
        const missionSub = document.getElementById('missionSubtitle');
        const startBtn = document.getElementById('startMissionBtn');
        const startBtnText = document.getElementById('startMissionBtnText');

        if (dueCount > 0) {
            if (missionTitle) missionTitle.textContent = 'Clear Your Spaced Repetition Queue';
            if (missionSub) {
                const weakText = weakSpot ? ` · Focus Slide ${weakSpot.slide_number}` : '';
                missionSub.textContent = `${dueCount} cards due today${weakText} · Daily target: 20 XP`;
            }
            if (startBtnText) startBtnText.textContent = `Start Deck Run (${dueCount} Due)`;
            if (startBtn) {
                startBtn.onclick = () => {
                    switchTab('tab-flashcards');
                    loadFlashcards();
                };
            }
        } else if (weakSpot) {
            if (missionTitle) missionTitle.textContent = `Conquer Weak Spot: Slide ${weakSpot.slide_number}`;
            if (missionSub) missionSub.textContent = `Current mastery is ${weakSpot.mastery_percent}%. Review key concepts & test recall.`;
            if (startBtnText) startBtnText.textContent = `Master Slide ${weakSpot.slide_number}`;
            if (startBtn) {
                startBtn.onclick = () => {
                    openSlideDetailModal(weakSpot.slide_number);
                };
            }
        } else {
            if (missionTitle) missionTitle.textContent = 'Challenge the Boss in Quiz Master';
            if (missionSub) missionSub.textContent = 'All cards reviewed! Test full presentation retention in Boss Battle mode.';
            if (startBtnText) startBtnText.textContent = 'Start Boss Battle';
            if (startBtn) {
                startBtn.onclick = () => {
                    switchTab('tab-quizmaster');
                    setQuizMasterMode('boss');
                };
            }
        }
    } catch (e) {
        console.warn('Failed to load mission data:', e);
    }
}

// ==========================================================================
// 4. API KEY LOGIC WITH LIVE VERIFICATION (Bug 8b Fix)
// ==========================================================================
function initApiKey() {
    const savedKey = localStorage.getItem('gemini_api_key');
    const input = document.getElementById('apiKeyInput');
    const saveBtn = document.getElementById('saveKeyBtn');
    const badge = document.getElementById('aiStatusBadge');
    const statusText = document.getElementById('aiStatusText');

    if (savedKey) {
        input.value = savedKey;
        verifyAndSetBadge(savedKey);
    }

    saveBtn.addEventListener('click', async () => {
        const val = input.value.trim();
        if (val) {
            localStorage.setItem('gemini_api_key', val);
            await verifyAndSetBadge(val, true);
        } else {
            localStorage.removeItem('gemini_api_key');
            updateBadge(false, 'Smart Local Mode');
            alert('API Key cleared. Switched to smart local mode.');
        }
    });

    async function verifyAndSetBadge(key, notify = false) {
        try {
            const res = await fetch('/api/ai/check', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ api_key: key })
            });
            const data = await res.json();
            if (data.status === 'valid') {
                updateBadge(true, 'Gemini AI Active');
                if (notify) alert('✅ Gemini API Key connected and verified! Full AI generation is active.');
            } else if (data.status === 'quota_exhausted') {
                updateBadge(false, 'Gemini Quota Exceeded');
                if (notify) alert('⚠️ Notice: Gemini API quota exceeded. Falling back to smart local mode.');
            } else {
                updateBadge(false, 'Invalid API Key');
                if (notify) alert('⚠️ Notice: Invalid Gemini API key. Running in smart local mode.');
            }
        } catch (e) {
            updateBadge(false, 'Smart Local Mode');
            if (notify) alert('Switched to smart local mode.');
        }
    }

    function updateBadge(isActive, text = 'Smart Local Mode') {
        if (!badge || !statusText) return;
        if (isActive) {
            badge.className = 'badge badge-active';
            statusText.textContent = text;
            badge.title = 'Gemini AI generative model is active.';
        } else {
            badge.className = 'badge badge-fallback';
            statusText.textContent = text;
            badge.title = 'Enter a valid Gemini API key to unlock full AI generation.';
        }
    }
}

function getApiKey() {
    return localStorage.getItem('gemini_api_key') || null;
}

// ==========================================================================
// 5. STAGED UPLOAD REVEAL & FILE HANDLING (Bug 8a Warning Display)
// ==========================================================================
function initFileUpload() {
    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('fileInput');
    const appendFileInput = document.getElementById('appendFileInput');
    const addDocsBtn = document.getElementById('addDocsBtn');
    const reuploadBtn = document.getElementById('reuploadBtn');

    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            dropZone.classList.add('drag-over');
        }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            dropZone.classList.remove('drag-over');
        }, false);
    });

    dropZone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        if (files && files.length > 0) {
            handleFileUpload(files, 'replace');
        }
    });

    fileInput.addEventListener('change', (e) => {
        if (e.target.files && e.target.files.length > 0) {
            handleFileUpload(e.target.files, 'replace');
        }
    });

    if (appendFileInput) {
        appendFileInput.addEventListener('change', (e) => {
            if (e.target.files && e.target.files.length > 0) {
                handleFileUpload(e.target.files, 'append');
            }
        });
    }

    if (addDocsBtn && appendFileInput) {
        addDocsBtn.addEventListener('click', () => {
            appendFileInput.click();
        });
    }

    reuploadBtn.addEventListener('click', () => {
        document.getElementById('workspaceSection').classList.add('hidden');
        document.getElementById('uploadSection').classList.remove('hidden');
        fileInput.value = '';
        if (appendFileInput) appendFileInput.value = '';
    });
}

async function handleFileUpload(files, mode = 'replace') {
    hideError();
    const fileList = Array.isArray(files) ? files : Array.from(files);
    if (!fileList || fileList.length === 0) return;

    for (const f of fileList) {
        const fname = f.name.toLowerCase();
        if (!fname.endsWith('.pptx') && !fname.endsWith('.ppt') && !fname.endsWith('.pdf')) {
            showError(`File "${f.name}" is unsupported. Please upload PowerPoint (.pptx / .ppt) or PDF (.pdf) files.`);
            return;
        }
    }

    const uploadSection = document.getElementById('uploadSection');
    const loadingOverlay = document.getElementById('loadingOverlay');
    const workspaceSection = document.getElementById('workspaceSection');
    const loadingTitle = document.getElementById('loadingTitle');
    const loadingText = document.getElementById('loadingText');

    if (loadingTitle) loadingTitle.textContent = 'Processing Knowledge Base...';
    if (loadingText) {
        loadingText.textContent = fileList.length > 1
            ? `Extracting slides & notes across ${fileList.length} documents...`
            : `Extracting text, slides, and presenter annotations...`;
    }

    // Set staged reveal progress steps
    const step1 = document.getElementById('step1');
    const step2 = document.getElementById('step2');
    const step3 = document.getElementById('step3');
    const step4 = document.getElementById('step4');

    function setStep(el, state) {
        if (!el) return;
        el.className = `stage-step ${state}`;
        if (state === 'done') {
            el.innerHTML = `<i class="fa-solid fa-circle-check" style="color: var(--accent-emerald);"></i> ${el.textContent.trim()}`;
        } else if (state === 'active') {
            el.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> ${el.textContent.trim()}`;
        }
    }

    setStep(step1, 'active');
    setStep(step2, 'pending');
    setStep(step3, 'pending');
    setStep(step4, 'pending');

    uploadSection.classList.add('hidden');
    loadingOverlay.classList.remove('hidden');

    const formData = new FormData();
    fileList.forEach(file => {
        formData.append('files', file);
    });

    try {
        setStep(step1, 'done');
        setStep(step2, 'active');

        const response = await fetch(`/api/upload?mode=${mode}`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Upload failed');
        }

        setStep(step2, 'done');
        setStep(step3, 'active');

        const data = await response.json();
        presentationData = data;
        currentDocFilter = 'ALL';

        setStep(step3, 'done');
        setStep(step4, 'active');

        // Check for Bug 8a corrupt XML warnings
        const warningBadge = document.getElementById('uploadWarningBadge');
        if (data.warnings && data.warnings.length > 0) {
            if (warningBadge) {
                warningBadge.classList.remove('hidden');
                warningBadge.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i> ${data.warnings.length} Warning(s)`;
                warningBadge.title = data.warnings.map(w => `Slide ${w.slide_number}: ${w.message}`).join('\n');
            }
        } else if (warningBadge) {
            warningBadge.classList.add('hidden');
        }

        if (mode === 'replace') {
            resetStudyStateContainers();
        }

        updateWorkspaceHeader(data);
        renderDocFilterBar(data.documents, data.filenames);
        renderSlides(data.slides);
        updateChatSuggestions(data.slides);

        await loadTodaysMission();
        await loadMasteryMap();

        setStep(step4, 'done');
        sounds.fanfare();

        setTimeout(() => {
            loadingOverlay.classList.add('hidden');
            workspaceSection.classList.remove('hidden');
        }, 400);

    } catch (err) {
        showError('Error parsing documents: ' + err.message);
        loadingOverlay.classList.add('hidden');
        if (!presentationData) {
            uploadSection.classList.remove('hidden');
        } else {
            workspaceSection.classList.remove('hidden');
        }
    }
}

function resetStudyStateContainers() {
    const summaryContainer = document.getElementById('summaryContainer');
    if (summaryContainer) {
        summaryContainer.innerHTML = `
            <div class="placeholder-state">
                <i class="fa-solid fa-book-open placeholder-icon" aria-hidden="true"></i>
                <p>Click below to generate an intuitive study guide from your slides & presenter notes.</p>
                <button class="btn btn-primary" onclick="loadStudySummary()">Generate Study Guide</button>
            </div>`;
    }

    const flashcardsContainer = document.getElementById('flashcardsContainer');
    if (flashcardsContainer) {
        flashcardsContainer.innerHTML = `
            <div class="placeholder-state">
                <i class="fa-solid fa-clone placeholder-icon" aria-hidden="true"></i>
                <p>Ready to practice active recall? Generate flashcards with 3D flip & SM-2 scheduling.</p>
                <button class="btn btn-primary" onclick="loadFlashcards()">Generate Flashcards</button>
            </div>`;
    }

    const quizContainer = document.getElementById('quizContainer');
    if (quizContainer) {
        quizContainer.innerHTML = `
            <div class="placeholder-state">
                <i class="fa-solid fa-graduation-cap placeholder-icon" aria-hidden="true"></i>
                <p>Ready for exam prep? Generate authentic 5-mark and 10-mark questions with marking schemes.</p>
                <button class="btn btn-primary" onclick="loadQuiz()">Generate Exam Pack</button>
            </div>`;
    }
    chatHistory = [];
}

function updateWorkspaceHeader(data) {
    const filenames = data.filenames || [data.filename || 'document'];
    const totalDocs = filenames.length;
    const totalSlides = data.total_slides || (data.slides ? data.slides.length : 0);

    const loadedFileNameEl = document.getElementById('loadedFileName');
    if (loadedFileNameEl) {
        loadedFileNameEl.textContent = totalDocs > 1 ? `${totalDocs} Documents Combined` : filenames[0];
    }

    const slideBadge = document.getElementById('slideCountBadge');
    if (slideBadge) {
        slideBadge.textContent = `${totalSlides} Slides / Pages Total`;
    }

    const docBadge = document.getElementById('docCountBadge');
    if (docBadge) {
        docBadge.textContent = `${totalDocs} Document${totalDocs > 1 ? 's' : ''}`;
    }

    const pillsContainer = document.getElementById('documentPillsContainer');
    if (pillsContainer) {
        pillsContainer.innerHTML = '';
        filenames.forEach(fn => {
            const pill = document.createElement('span');
            pill.className = 'doc-pill';
            const icon = fn.toLowerCase().endsWith('.pdf') ? 'fa-file-pdf' : 'fa-file-powerpoint';
            const count = (data.slides || []).filter(s => s.doc_name === fn).length;
            pill.innerHTML = `<i class="fa-solid ${icon}"></i> <strong>${escapeHtml(fn)}</strong>${count > 0 ? ` (${count} slides)` : ''}`;
            pillsContainer.appendChild(pill);
        });
    }

    const tabSlideCount = document.getElementById('tabSlideCount');
    if (tabSlideCount) tabSlideCount.textContent = totalSlides;

    const chatStatus = document.getElementById('chatContextStatus');
    if (chatStatus) {
        chatStatus.textContent = `Ready • ${totalDocs} document(s) & ${totalSlides} slides indexed`;
    }
}

// ==========================================================================
// 6. MASTERY MAP & SLIDES (Replacing boring list as default view)
// ==========================================================================
function initMasteryViewSwitch() {
    const mapBtn = document.getElementById('viewMasteryMapBtn');
    const listBtn = document.getElementById('viewDocListBtn');
    const mapSec = document.getElementById('masteryMapSection');
    const listSec = document.getElementById('docListSection');

    if (mapBtn && listBtn && mapSec && listSec) {
        mapBtn.addEventListener('click', () => {
            mapBtn.className = 'btn btn-primary btn-sm active';
            listBtn.className = 'btn btn-outline btn-sm';
            mapSec.classList.remove('hidden');
            listSec.classList.add('hidden');
        });

        listBtn.addEventListener('click', () => {
            listBtn.className = 'btn btn-primary btn-sm active';
            mapBtn.className = 'btn btn-outline btn-sm';
            listSec.classList.remove('hidden');
            mapSec.classList.add('hidden');
        });
    }
}

async function loadMasteryMap() {
    try {
        const res = await fetch('/api/study/mastery');
        if (!res.ok) return;
        const data = await res.json();

        // Update stats
        const pctEl = document.getElementById('masteryOverallPercent');
        if (pctEl) pctEl.textContent = `${data.overall_mastery_percent || 0}%`;

        let mastered = 0, learning = 0;
        const weakCount = (data.weak_spots || []).length;

        (data.slides || []).forEach(s => {
            if (s.status === 'mastered') mastered++;
            else if (s.status === 'learning') learning++;
        });

        const mastEl = document.getElementById('masteryMasteredCount');
        if (mastEl) mastEl.textContent = mastered;

        const learnEl = document.getElementById('masteryLearningCount');
        if (learnEl) learnEl.textContent = learning;

        const weakEl = document.getElementById('masteryWeakSpotsCount');
        if (weakEl) weakEl.textContent = weakCount;

        // Render Tiles Grid
        const grid = document.getElementById('masteryTilesGrid');
        if (!grid) return;
        grid.innerHTML = '';

        const weakSlideNums = new Set((data.weak_spots || []).map(w => w.slide_number));

        (data.slides || []).forEach(slide => {
            const isWeak = weakSlideNums.has(slide.slide_number);
            const hasWarning = slide.has_warning;

            const tile = document.createElement('div');
            let classes = `mastery-tile ${slide.status || 'empty'}`;
            if (isWeak) classes += ' weak';
            if (hasWarning) classes += ' warning';
            tile.className = classes;

            const warningIcon = hasWarning ? `<span class="tile-warning-badge" title="${escapeHtml(slide.warning_message || 'Corrupt XML detected')}">⚠️</span>` : '';
            const weakBadge = isWeak ? `<span class="tile-weak-badge">🎯 Weak</span>` : '';

            tile.innerHTML = `
                <div class="tile-top-row">
                    <span class="tile-num">Slide ${slide.slide_number}</span>
                    <div style="display:flex; gap:4px; align-items:center;">
                        ${weakBadge}
                        ${warningIcon}
                        <span class="tile-pct">${slide.mastery_percent}%</span>
                    </div>
                </div>
                <div class="tile-title" title="${escapeHtml(slide.title)}">${escapeHtml(slide.title)}</div>
                <div class="tile-progress-track">
                    <div class="tile-progress-fill" style="width: ${slide.mastery_percent}%;"></div>
                </div>
                <div class="tile-meta">${slide.repetitions || 0} reviews · ease ${Number(slide.ease_factor || 2.5).toFixed(1)}</div>
            `;

            tile.onclick = () => openSlideDetailModal(slide.slide_number);
            grid.appendChild(tile);
        });

    } catch (e) {
        console.warn('Failed to load mastery map:', e);
    }
}

function openSlideDetailModal(slideNumber) {
    if (!presentationData || !presentationData.slides) return;
    const slide = presentationData.slides.find(s => s.slide_number === slideNumber) || presentationData.slides[0];
    if (!slide) return;

    const modal = document.getElementById('slideDetailModal');
    const titleEl = document.getElementById('modalSlideTitle');
    const badgeEl = document.getElementById('modalSlideBadge');
    const masteryBadgeEl = document.getElementById('modalMasteryBadge');
    const weakBadgeEl = document.getElementById('modalWeakSpotBadge');
    const warningBadgeEl = document.getElementById('modalWarningBadge');
    const warningAlertEl = document.getElementById('modalWarningAlert');
    const contentEl = document.getElementById('modalSlideContent');
    const notesSecEl = document.getElementById('modalNotesSection');
    const notesEl = document.getElementById('modalSlideNotes');
    const teachBtn = document.getElementById('modalTeachMeBtn');

    if (badgeEl) badgeEl.textContent = `Slide ${slide.slide_number}`;
    if (titleEl) titleEl.textContent = slide.title || 'Untitled Slide';

    // Check warning
    if (slide.has_warning) {
        if (warningBadgeEl) warningBadgeEl.classList.remove('hidden');
        if (warningAlertEl) {
            warningAlertEl.classList.remove('hidden');
            const alertText = document.getElementById('modalWarningText');
            if (alertText) alertText.textContent = slide.warning_message || 'Slide XML could not be fully parsed.';
        }
    } else {
        if (warningBadgeEl) warningBadgeEl.classList.add('hidden');
        if (warningAlertEl) warningAlertEl.classList.add('hidden');
    }

    // Populate content
    if (contentEl) {
        let contentHtml = '';
        if (slide.text_content && slide.text_content.length > 0) {
            contentHtml += `<ul class="slide-text-list">` + slide.text_content.map(t => `<li>${escapeHtml(t)}</li>`).join('') + `</ul>`;
        }
        if (slide.tables && slide.tables.length > 0) {
            slide.tables.forEach(tableData => {
                contentHtml += `<table class="slide-table">`;
                tableData.forEach((row, rIdx) => {
                    contentHtml += `<tr>` + row.map(cell => `<${rIdx === 0 ? 'th' : 'td'}>${escapeHtml(cell)}</${rIdx === 0 ? 'th' : 'td'}>`).join('') + `</tr>`;
                });
                contentHtml += `</table>`;
            });
        }
        if (!contentHtml) {
            contentHtml = '<p style="color: var(--text-muted);">No textual content found on this slide.</p>';
        }
        contentEl.innerHTML = contentHtml;
    }

    // Populate Speaker Notes
    if (notesSecEl && notesEl) {
        if (slide.speaker_notes && slide.speaker_notes.trim().length > 0) {
            notesSecEl.classList.remove('hidden');
            notesEl.innerHTML = `<p>${escapeHtml(slide.speaker_notes)}</p>`;
        } else {
            notesSecEl.classList.add('hidden');
        }
    }

    if (teachBtn) {
        teachBtn.onclick = () => {
            closeSlideDetailModal();
            teachSlide(slide.slide_number, slide.title, slide.doc_name);
        };
    }

    if (modal) modal.classList.remove('hidden');
}

function closeSlideDetailModal() {
    const modal = document.getElementById('slideDetailModal');
    if (modal) modal.classList.add('hidden');
}

// Render Document Filter Chips & Traditional Slides List View
function renderDocFilterBar(documents, filenames) {
    const filterContainer = document.getElementById('docFilterContainer');
    if (!filterContainer) return;

    if (!filenames || filenames.length <= 1) {
        filterContainer.innerHTML = '';
        filterContainer.style.display = 'none';
        return;
    }

    filterContainer.style.display = 'flex';
    filterContainer.innerHTML = '';

    const allBtn = document.createElement('button');
    allBtn.className = `doc-filter-chip ${currentDocFilter === 'ALL' ? 'active' : ''}`;
    allBtn.innerHTML = `<i class="fa-solid fa-layer-group"></i> All Documents (${presentationData.total_slides})`;
    allBtn.onclick = () => {
        currentDocFilter = 'ALL';
        updateFilterChipActive(allBtn);
        renderSlides(presentationData.slides);
    };
    filterContainer.appendChild(allBtn);

    filenames.forEach(fn => {
        const docSlides = (presentationData.slides || []).filter(s => s.doc_name === fn);
        const chip = document.createElement('button');
        chip.className = `doc-filter-chip ${currentDocFilter === fn ? 'active' : ''}`;
        const icon = fn.toLowerCase().endsWith('.pdf') ? 'fa-file-pdf' : 'fa-file-powerpoint';
        chip.innerHTML = `<i class="fa-solid ${icon}"></i> ${escapeHtml(fn)} (${docSlides.length})`;
        chip.onclick = () => {
            currentDocFilter = fn;
            updateFilterChipActive(chip);
            renderSlides(presentationData.slides);
        };
        filterContainer.appendChild(chip);
    });
}

function updateFilterChipActive(activeBtn) {
    const chips = document.querySelectorAll('.doc-filter-chip');
    chips.forEach(c => c.classList.remove('active'));
    activeBtn.classList.add('active');
}

function renderSlides(slides) {
    const container = document.getElementById('slidesContainer');
    if (!container) return;
    container.innerHTML = '';

    const filteredSlides = (currentDocFilter && currentDocFilter !== 'ALL')
        ? slides.filter(s => s.doc_name === currentDocFilter)
        : slides;

    if (filteredSlides.length === 0) {
        container.innerHTML = '<div style="padding: 30px; text-align: center; color: var(--text-muted);">No slides found matching this filter.</div>';
        return;
    }

    const hasMultiDocs = presentationData && presentationData.filenames && presentationData.filenames.length > 1;

    filteredSlides.forEach(slide => {
        const card = document.createElement('div');
        card.className = 'slide-card';

        const sNum = slide.doc_slide_number || slide.slide_number;
        const gNum = slide.slide_number;

        const header = document.createElement('div');
        header.className = 'slide-card-header';
        header.innerHTML = `
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                <span class="slide-title">${escapeHtml(slide.title)}</span>
                <span class="slide-num-badge">Slide/Page ${sNum}${hasMultiDocs ? ` (Global #${gNum})` : ''}</span>
                ${hasMultiDocs && slide.doc_name ? `<span class="slide-doc-badge"><i class="fa-solid fa-file"></i> ${escapeHtml(slide.doc_name)}</span>` : ''}
                ${slide.has_warning ? `<span class="badge badge-warning" title="${escapeHtml(slide.warning_message || 'Corrupt XML')}">⚠️ Parse Warning</span>` : ''}
            </div>
            <button class="teach-slide-btn" onclick="teachSlide(${gNum}, '${escapeHtml(slide.title).replace(/'/g, "\\'")}', '${escapeHtml(slide.doc_name || '').replace(/'/g, "\\'")}')">
                <i class="fa-solid fa-graduation-cap"></i> Teach Me This
            </button>
        `;

        const body = document.createElement('div');
        body.className = 'slide-card-body';

        if (slide.text_content && slide.text_content.length > 0) {
            const list = document.createElement('ul');
            list.className = 'slide-text-list';
            slide.text_content.forEach(txt => {
                const li = document.createElement('li');
                li.textContent = txt;
                list.appendChild(li);
            });
            body.appendChild(list);
        }

        if (slide.tables && slide.tables.length > 0) {
            slide.tables.forEach(tableData => {
                const table = document.createElement('table');
                table.className = 'slide-table';
                tableData.forEach((row, rIdx) => {
                    const tr = document.createElement('tr');
                    row.forEach(cell => {
                        const cellTag = rIdx === 0 ? 'th' : 'td';
                        const el = document.createElement(cellTag);
                        el.textContent = cell;
                        tr.appendChild(el);
                    });
                    table.appendChild(tr);
                });
                body.appendChild(table);
            });
        }

        const notesBox = document.createElement('div');
        notesBox.className = 'speaker-notes-box';
        const hasNotes = slide.speaker_notes && slide.speaker_notes.trim().length > 0;
        notesBox.innerHTML = `
            <div class="speaker-notes-header">
                <i class="fa-solid fa-note-sticky"></i> Speaker / Document Notes:
            </div>
            <div class="speaker-notes-content">${hasNotes ? escapeHtml(slide.speaker_notes) : '<em>No extra speaker notes or annotations on this page.</em>'}</div>
        `;
        body.appendChild(notesBox);

        card.appendChild(header);
        card.appendChild(body);
        container.appendChild(card);
    });
}

function teachSlide(num, title, docName) {
    switchTab('tab-chat');
    selectTeacherPersona('socratic');
    const prompt = `Teach me Page/Slide ${num}: "${title}". Explain all points and presenter annotations step-by-step with an intuitive analogy.`;
    sendSuggestedQuestion(prompt);
}

// Search & Export
function initSearch() {
    const searchInput = document.getElementById('slideSearchInput');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            const query = e.target.value.toLowerCase().trim();
            const cards = document.querySelectorAll('.slide-card');
            cards.forEach(card => {
                const text = card.textContent.toLowerCase();
                card.style.display = (!query || text.includes(query)) ? 'block' : 'none';
            });
        });
    }
}

function initExportText() {
    const txtBtn = document.getElementById('exportTextBtn');
    if (txtBtn) {
        txtBtn.addEventListener('click', () => { window.location.href = '/api/export/text'; });
    }
    const jsonBtn = document.getElementById('exportJsonBtn');
    if (jsonBtn) {
        jsonBtn.addEventListener('click', () => { window.location.href = '/api/export/json'; });
    }
}

// ==========================================================================
// 7. TAB NAVIGATION & HOTKEYS
// ==========================================================================
function initTabs() {
    const tabBtns = document.querySelectorAll('.tab-btn');
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetTab = btn.getAttribute('data-tab');
            switchTab(btn.id, targetTab);
        });
    });

    document.getElementById('generateSummaryBtn').addEventListener('click', () => loadStudySummary(true));
    document.getElementById('generateFlashcardsBtn').addEventListener('click', regenerateFlashcards);
    document.getElementById('generateQuizBtn').addEventListener('click', () => loadQuiz(true));
}

function switchTab(btnId, targetTabId = null) {
    const btn = document.getElementById(btnId) || document.querySelector(`.tab-btn[data-tab="${btnId}"]`);
    if (!btn) return;

    const targetTab = targetTabId || btn.getAttribute('data-tab');
    document.querySelectorAll('.tab-btn').forEach(b => {
        b.classList.remove('active');
        b.setAttribute('aria-selected', 'false');
    });
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));

    btn.classList.add('active');
    btn.setAttribute('aria-selected', 'true');
    const panel = document.getElementById(targetTab);
    if (panel) panel.classList.add('active');
}

// ==========================================================================
// 8. INTERACTIVE STUDY GUIDE (Claude Style, TL;DR & Hidden Clues)
// ==========================================================================
function toggleTldrMode() {
    tldrModeActive = !tldrModeActive;
    const btnText = document.getElementById('tldrBtnText');
    const container = document.getElementById('summaryContainer');
    if (btnText) btnText.textContent = tldrModeActive ? '10s TL;DR: ON' : '10s TL;DR: OFF';
    if (container) {
        if (tldrModeActive) container.classList.add('tldr-mode');
        else container.classList.remove('tldr-mode');
    }
}

async function loadStudySummary(forceRefresh = false) {
    hideError();
    const container = document.getElementById('summaryContainer');
    container.innerHTML = `<div class="loading-overlay"><div class="spinner"></div><p>Synthesizing intuitive Claude-style study guide with analogies, clues & exam traps...</p></div>`;

    try {
        const res = await fetch('/api/study/summary', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_key: getApiKey(), force_refresh: forceRefresh })
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Failed to generate study guide');
        }

        const data = await res.json();
        let html = '';

        // 1. Hero Big Picture
        html += `
            <div class="summary-hero-card">
                <div class="summary-hero-badge"><i class="fa-solid fa-graduation-cap"></i> Master Study Blueprint</div>
                <h2>${escapeHtml(data.title || 'Presentation Master Study Guide')}</h2>
                ${data.big_picture ? `<div class="summary-big-picture"><strong>🎯 The Big Picture:</strong> ${escapeHtml(data.big_picture)}</div>` : ''}
                <p class="summary-overview-text">${escapeHtml(data.summary || '')}</p>
            </div>
        `;

        // 2. Simple Analogies
        if (data.analogies && data.analogies.length > 0) {
            html += `
                <div class="summary-section">
                    <div class="section-title-row">
                        <span class="section-icon-badge badge-analogy"><i class="fa-solid fa-lightbulb"></i></span>
                        <div>
                            <h3>Simple Analogies & Mental Models</h3>
                            <p class="section-subtitle">Real-world comparisons that make complex mechanisms intuitive.</p>
                        </div>
                    </div>
                    <div class="analogies-grid">
            `;
            data.analogies.forEach(a => {
                html += `
                    <div class="analogy-card">
                        <div class="analogy-topic"><i class="fa-solid fa-bolt"></i> ${escapeHtml(a.topic || 'Core Concept')}</div>
                        <div class="analogy-quote"><span class="analogy-lead">💡 Analogy:</span> ${escapeHtml(a.analogy || '')}</div>
                        ${a.why_it_works ? `<div class="analogy-why"><strong>Why it works:</strong> ${escapeHtml(a.why_it_works)}</div>` : ''}
                    </div>
                `;
            });
            html += `</div></div>`;
        }

        // 3. Core Concepts with 10s TL;DR & "Test me" micro-quizzes
        if (data.key_concepts && data.key_concepts.length > 0) {
            html += `
                <div class="summary-section">
                    <div class="section-title-row">
                        <span class="section-icon-badge badge-concepts"><i class="fa-solid fa-cubes"></i></span>
                        <div>
                            <h3>Core Concepts & Step-by-Step Logic</h3>
                            <p class="section-subtitle">Plain-English explanations and step-by-step processes.</p>
                        </div>
                    </div>
                    <div class="concept-grid">
            `;
            data.key_concepts.forEach(c => {
                let stepsHtml = '';
                if (c.how_it_works_steps && Array.isArray(c.how_it_works_steps) && c.how_it_works_steps.length > 0) {
                    stepsHtml = `
                        <div class="concept-steps">
                            <div class="steps-title"><i class="fa-solid fa-list-ol"></i> Step-by-Step Process:</div>
                            <ol>${c.how_it_works_steps.map(s => `<li>${escapeHtml(s)}</li>`).join('')}</ol>
                        </div>
                    `;
                }

                html += `
                    <div class="concept-card">
                        <div class="concept-card-header">
                            <h4>${escapeHtml(c.concept)}</h4>
                            ${c.slides_referenced ? `<span class="concept-slide-tag">📌 ${escapeHtml(c.slides_referenced)}</span>` : ''}
                        </div>
                        <div class="concept-tldr-box">
                            <strong>⚡ 10s TL;DR:</strong> ${escapeHtml(c.explanation.slice(0, 110))}...
                        </div>
                        <p class="concept-explanation">${escapeHtml(c.explanation)}</p>
                        ${c.real_world_analogy ? `<div class="concept-analogy-box"><i class="fa-solid fa-wand-magic-sparkles"></i> <em>${escapeHtml(c.real_world_analogy)}</em></div>` : ''}
                        ${stepsHtml}
                        <div style="margin-top: 12px; display: flex; gap: 8px;">
                            <button class="btn btn-outline btn-sm" onclick="startConceptMicroQuiz('${escapeHtml(c.concept).replace(/'/g, "\\'")}')">
                                <i class="fa-solid fa-bolt"></i> 🎯 Test Me on This
                            </button>
                        </div>
                    </div>
                `;
            });
            html += `</div></div>`;
        }

        // 4. Click-to-Reveal Hidden Clue Cards (Speaker Notes)
        if (data.speaker_note_highlights && data.speaker_note_highlights.length > 0) {
            html += `
                <div class="summary-section">
                    <div class="section-title-row">
                        <span class="section-icon-badge badge-notes"><i class="fa-solid fa-user-secret"></i></span>
                        <div>
                            <h3>Presenter Notes & Hidden Exam Clues</h3>
                            <p class="section-subtitle">Click to reveal instructor test hints extracted from annotations.</p>
                        </div>
                    </div>
                    <div class="hidden-clues-grid">
            `;
            data.speaker_note_highlights.forEach((h, idx) => {
                html += `
                    <div class="hidden-clue-card" onclick="toggleClueCard('clue_${idx}')">
                        <div class="clue-prompt">
                            <i class="fa-solid fa-key"></i> <span>Instructor Secret Clue #${idx + 1} (Click to reveal)</span>
                        </div>
                        <div id="clue_${idx}" class="clue-revealed hidden">
                            <p>${escapeHtml(h)}</p>
                        </div>
                    </div>
                `;
            });
            html += `</div></div>`;
        }

        // 5. Exam Traps & Common Confusions
        if (data.exam_traps && data.exam_traps.length > 0) {
            html += `
                <div class="summary-section">
                    <div class="section-title-row">
                        <span class="section-icon-badge badge-traps"><i class="fa-solid fa-triangle-exclamation"></i></span>
                        <div>
                            <h3>⚠️ Exam Traps & Common Mistakes</h3>
                            <p class="section-subtitle">Classic pitfalls and how to guarantee full marks.</p>
                        </div>
                    </div>
                    <div class="traps-grid">
            `;
            data.exam_traps.forEach(t => {
                html += `
                    <div class="trap-card">
                        <div class="trap-warning"><i class="fa-solid fa-circle-xmark"></i> <strong>Trap:</strong> ${escapeHtml(t.trap || '')}</div>
                        <div class="trap-fix"><i class="fa-solid fa-circle-check"></i> <strong>The Fix:</strong> ${escapeHtml(t.fix || '')}</div>
                    </div>
                `;
            });
            html += `</div></div>`;
        }

        container.innerHTML = html;
        if (tldrModeActive) container.classList.add('tldr-mode');

    } catch (err) {
        showError('Failed to load study guide: ' + err.message);
        container.innerHTML = `<p class="placeholder-state" style="color: var(--danger);">${escapeHtml(err.message)}</p>`;
    }
}

function toggleClueCard(id) {
    const el = document.getElementById(id);
    if (!el) return;
    const isHidden = el.classList.contains('hidden');
    if (isHidden) {
        el.classList.remove('hidden');
        sounds.flip();
    } else {
        el.classList.add('hidden');
    }
}

function startConceptMicroQuiz(conceptName) {
    switchTab('tab-quizmaster');
    const topicInput = document.getElementById('qmTopic');
    if (topicInput) topicInput.value = conceptName;
    const countSelect = document.getElementById('qmCount');
    if (countSelect) countSelect.value = "3";
    setQuizMasterMode('boss');
    startQuizMasterExam();
}

// ==========================================================================
// 9. FLASHCARDS -> "DECK RUN" WITH SM-2 & 3D FLIP ANIMATION
// ==========================================================================
let comboStreak = 0;
let maxComboStreak = 0;
let masteredInDeckRun = 0;

async function loadFlashcards() {
    hideError();
    const container = document.getElementById('flashcardsContainer');
    const header = document.getElementById('deckRunHeader');
    const completedScreen = document.getElementById('deckCompletedScreen');

    if (completedScreen) completedScreen.classList.add('hidden');

    try {
        const apiKeyParam = getApiKey() ? `?api_key=${encodeURIComponent(getApiKey())}` : '';
        const res = await fetch(`/api/study/flashcards/due${apiKeyParam}`);

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Failed to fetch due flashcards');
        }

        const data = await res.json();
        flashcardsList = data.due_flashcards || [];
        currentFlashcardIndex = 0;
        comboStreak = 0;
        maxComboStreak = 0;
        masteredInDeckRun = 0;

        const dueBadge = document.getElementById('dueCardsBadge');
        if (dueBadge) {
            dueBadge.textContent = `${data.total_due || 0} Due`;
        }

        if (flashcardsList.length === 0) {
            if (header) header.classList.add('hidden');
            container.innerHTML = `
                <div class="placeholder-state">
                    <i class="fa-solid fa-circle-check placeholder-icon" style="color: var(--accent-emerald);"></i>
                    <h3>🎉 All Caught Up!</h3>
                    <p>No cards due for review right now. Outstanding dedication! Come back tomorrow for your next spaced repetition cycle.</p>
                </div>
            `;
            return;
        }

        if (header) header.classList.remove('hidden');
        renderCurrentFlashcard();

    } catch (err) {
        showError('Failed to load flashcards: ' + err.message);
        container.innerHTML = `<p class="placeholder-state" style="color: var(--danger);">${escapeHtml(err.message)}</p>`;
    }
}

async function regenerateFlashcards() {
    try {
        const res = await fetch('/api/study/flashcards', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_key: getApiKey(), force_refresh: true })
        });
        if (!res.ok) throw new Error('Failed to regenerate flashcards');
        await loadFlashcards();
    } catch (err) {
        showError(err.message);
    }
}

function renderCurrentFlashcard() {
    const container = document.getElementById('flashcardsContainer');
    if (!flashcardsList || flashcardsList.length === 0) {
        loadFlashcards();
        return;
    }

    const card = flashcardsList[currentFlashcardIndex];
    const total = flashcardsList.length;

    // Update Progress Ring
    const pct = Math.round(((currentFlashcardIndex) / total) * 100);
    const ringFill = document.getElementById('deckRingFill');
    if (ringFill) ringFill.setAttribute('stroke-dasharray', `${pct}, 100`);

    const counterText = document.getElementById('deckCounterText');
    if (counterText) counterText.textContent = `${currentFlashcardIndex + 1} / ${total}`;

    // Update Combo Badge
    const comboBadge = document.getElementById('comboCounterBadge');
    const comboNum = document.getElementById('comboStreakNum');
    if (comboBadge && comboNum) {
        if (comboStreak >= 2) {
            comboNum.textContent = comboStreak;
            comboBadge.classList.remove('hidden');
        } else {
            comboBadge.classList.add('hidden');
        }
    }

    container.innerHTML = `
        <div id="activeCardWrapper" class="flashcard-wrapper" onclick="toggleCardFlip()" role="button" tabindex="0" aria-label="Flip flashcard">
            <div id="activeFlashcard" class="flashcard">
                <div class="card-face card-front">
                    <div style="display: flex; justify-content: space-between; align-items: center; width: 100%;">
                        <span class="card-category">${escapeHtml(card.category || 'Core Concept')}</span>
                        <span class="card-slide-tag">${card.slide_number ? `📌 Slide ${card.slide_number}` : ''}</span>
                    </div>
                    <div class="card-text">${escapeHtml(card.front)}</div>
                    <span class="card-instruction"><i class="fa-solid fa-hand-pointer"></i> Click card or press <strong>Space</strong> to flip</span>
                </div>
                <div class="card-face card-back">
                    <span class="card-category">Model Answer & Recall Rating</span>
                    <div class="card-text" style="font-size: 15px;">${escapeHtml(card.back)}</div>

                    <div class="sm2-rating-container" onclick="event.stopPropagation()">
                        <button class="sm2-rating-btn btn-again" onclick="submitCardReview('${card.card_id}', 'again')">
                            <span>🔴 Again</span>
                            <span style="font-size: 10.5px; opacity: 0.85;">1 day</span>
                        </button>
                        <button class="sm2-rating-btn btn-hard" onclick="submitCardReview('${card.card_id}', 'hard')">
                            <span>🟠 Hard</span>
                            <span style="font-size: 10.5px; opacity: 0.85;">Harder</span>
                        </button>
                        <button class="sm2-rating-btn btn-good" onclick="submitCardReview('${card.card_id}', 'good')">
                            <span>🟢 Good</span>
                            <span style="font-size: 10.5px; opacity: 0.85;">Normal</span>
                        </button>
                        <button class="sm2-rating-btn btn-easy" onclick="submitCardReview('${card.card_id}', 'easy')">
                            <span>🔵 Easy</span>
                            <span style="font-size: 10.5px; opacity: 0.85;">Bonus</span>
                        </button>
                    </div>
                </div>
            </div>
        </div>
        <div class="flashcard-controls">
            <span class="deck-progress">Card ${currentFlashcardIndex + 1} of ${total} · Shortkeys: <strong>Space</strong> flip, <strong>1-4</strong> rate</span>
        </div>
    `;
}

function toggleCardFlip() {
    const cardEl = document.getElementById('activeFlashcard');
    if (cardEl) {
        cardEl.classList.toggle('flipped');
        sounds.flip();
    }
}

// Global Keyboard Handler for Deck Run
document.addEventListener('keydown', (e) => {
    const flashTab = document.getElementById('flashcardsTab');
    if (!flashTab || !flashTab.classList.contains('active')) return;
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

    if (e.code === 'Space') {
        e.preventDefault();
        toggleCardFlip();
    } else if (flashcardsList.length > 0 && currentFlashcardIndex < flashcardsList.length) {
        const card = flashcardsList[currentFlashcardIndex];
        if (e.key === '1') submitCardReview(card.card_id, 'again');
        else if (e.key === '2') submitCardReview(card.card_id, 'hard');
        else if (e.key === '3') submitCardReview(card.card_id, 'good');
        else if (e.key === '4') submitCardReview(card.card_id, 'easy');
    }
});

async function submitCardReview(cardId, rating) {
    hideError();
    const cardEl = document.getElementById('activeFlashcard');

    if (rating === 'again') {
        // Gentle safe shake without being punishing
        if (cardEl) {
            cardEl.classList.add('shake-again');
            setTimeout(() => cardEl.classList.remove('shake-again'), 400);
        }
        sounds.again();
        comboStreak = 0;
    } else if (rating === 'good' || rating === 'easy') {
        comboStreak++;
        if (comboStreak > maxComboStreak) maxComboStreak = comboStreak;
        masteredInDeckRun++;
        if (comboStreak >= 3) sounds.combo();
        else sounds.correct();
    } else {
        sounds.flip();
    }

    sessionTracker.cardsReviewed++;
    sessionTracker.xpEarned += (rating === 'again' ? 5 : (rating === 'easy' ? 20 : 15));

    try {
        const res = await fetch('/api/study/flashcards/review', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ card_id: cardId, rating: rating })
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Failed to submit review');
        }
    } catch (err) {
        console.warn('Review submission warning:', err.message);
    }

    // Advance to next card or complete deck
    currentFlashcardIndex++;
    if (currentFlashcardIndex < flashcardsList.length) {
        renderCurrentFlashcard();
    } else {
        showDeckRunCompletedScreen();
    }
}

function showDeckRunCompletedScreen() {
    const container = document.getElementById('flashcardsContainer');
    const header = document.getElementById('deckRunHeader');
    const completedScreen = document.getElementById('deckCompletedScreen');

    if (container) container.innerHTML = '';
    if (header) header.classList.add('hidden');
    if (completedScreen) completedScreen.classList.remove('hidden');

    const summaryText = document.getElementById('deckCompletedSummaryText');
    if (summaryText) {
        summaryText.textContent = `You completed all ${flashcardsList.length} cards in this review run. Your memory pathways are strengthening!`;
    }

    const mastCount = document.getElementById('compMasteredCount');
    if (mastCount) mastCount.textContent = masteredInDeckRun;

    const maxCombo = document.getElementById('compMaxCombo');
    if (maxCombo) maxCombo.textContent = `${maxComboStreak}x`;

    const nextRev = document.getElementById('compNextReview');
    if (nextRev) nextRev.textContent = 'Tomorrow';

    sounds.fanfare();
    triggerConfetti();

    // Refresh today's mission and mastery map
    loadTodaysMission();
    loadMasteryMap();
}

function restartDeckRun() {
    loadFlashcards();
}

// ==========================================================================
// 10. HAND-ROLLED CANVAS CONFETTI (Zero external dependencies)
// ==========================================================================
function triggerConfetti() {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        return; // Respect reduced motion preferences
    }

    const canvas = document.getElementById('confettiCanvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    canvas.width = canvas.parentElement.clientWidth || 500;
    canvas.height = canvas.parentElement.clientHeight || 350;

    const colors = ['#e07a5f', '#38bdf8', '#a855f7', '#10b981', '#f59e0b'];
    const particles = [];

    for (let i = 0; i < 70; i++) {
        particles.push({
            x: canvas.width / 2,
            y: canvas.height / 2,
            r: Math.random() * 5 + 3,
            color: colors[Math.floor(Math.random() * colors.length)],
            vx: (Math.random() - 0.5) * 12,
            vy: (Math.random() - 0.8) * 14,
            gravity: 0.35,
            rotation: Math.random() * 360,
            vRot: (Math.random() - 0.5) * 10
        });
    }

    let frame = 0;
    function render() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        let alive = false;

        particles.forEach(p => {
            p.x += p.vx;
            p.y += p.vy;
            p.vy += p.gravity;
            p.rotation += p.vRot;

            if (p.y < canvas.height + 20) {
                alive = true;
                ctx.save();
                ctx.translate(p.x, p.y);
                ctx.rotate((p.rotation * Math.PI) / 180);
                ctx.fillStyle = p.color;
                ctx.fillRect(-p.r, -p.r, p.r * 2, p.r * 1.5);
                ctx.restore();
            }
        });

        frame++;
        if (alive && frame < 150) {
            requestAnimationFrame(render);
        } else {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
        }
    }

    requestAnimationFrame(render);
}

// ==========================================================================
// 11. UNIVERSITY EXAM PREPARATION (5-Mark, 10-Mark & Practice MCQs)
// ==========================================================================
let examPackData = {
    five_mark_questions: [],
    ten_mark_questions: [],
    practice_mcqs: []
};
let currentExamFilter = 'all';

async function loadQuiz(forceRefresh = false) {
    hideError();
    const container = document.getElementById('quizContainer');
    const filterBar = document.getElementById('examFilterBar');
    container.innerHTML = `<div class="loading-overlay"><div class="spinner"></div><p>Synthesizing authentic 5-mark and 10-mark university questions, marking rubrics, and analogies...</p></div>`;

    try {
        const res = await fetch('/api/study/quiz', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_key: getApiKey(), force_refresh: forceRefresh })
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Failed to generate exam pack');
        }

        const data = await res.json();
        examPackData.five_mark_questions = data.five_mark_questions || [];
        examPackData.ten_mark_questions = data.ten_mark_questions || [];
        examPackData.practice_mcqs = data.practice_mcqs || data.quiz || [];
        quizList = examPackData.practice_mcqs;

        const fiveBadge = document.getElementById('fiveMarkBadge');
        if (fiveBadge) fiveBadge.textContent = examPackData.five_mark_questions.length;

        const tenBadge = document.getElementById('tenMarkBadge');
        if (tenBadge) tenBadge.textContent = examPackData.ten_mark_questions.length;

        const mcqBadge = document.getElementById('mcqBadge');
        if (mcqBadge) mcqBadge.textContent = examPackData.practice_mcqs.length;

        if (filterBar) filterBar.style.display = 'flex';
        renderExamPack();

    } catch (err) {
        showError('Failed to load exam pack: ' + err.message);
        container.innerHTML = `<p class="placeholder-state" style="color: var(--danger);">${escapeHtml(err.message)}</p>`;
    }
}

function filterExamCategory(category) {
    currentExamFilter = category;
    const filterBtns = document.querySelectorAll('.exam-filter-btn');
    filterBtns.forEach(btn => {
        if (btn.getAttribute('data-filter') === category) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
    renderExamPack();
}

function renderExamPack() {
    const container = document.getElementById('quizContainer');
    if (!container) return;
    container.innerHTML = '';
    const filter = currentExamFilter;

    // 1. Render 5-Mark Questions
    if ((filter === 'all' || filter === '5mark') && examPackData.five_mark_questions.length > 0) {
        if (filter === 'all') {
            const div = document.createElement('div');
            div.className = 'exam-section-divider';
            div.innerHTML = `<div class="exam-section-title"><span class="exam-type-badge badge-5m"><i class="fa-solid fa-bolt"></i> Section A: 5-Mark Conceptual Questions</span></div>`;
            container.appendChild(div);
        }

        examPackData.five_mark_questions.forEach((q, idx) => {
            const card = document.createElement('div');
            card.className = 'exam-q-card five-mark-card';
            let rubricHtml = (q.marking_rubric || []).map(r => `<li><i class="fa-solid fa-check-double"></i> ${escapeHtml(r)}</li>`).join('');

            card.innerHTML = `
                <div class="exam-q-header">
                    <div class="exam-q-tags">
                        <span class="exam-points-badge badge-5m">⚡ 5 MARKS</span>
                        <span class="exam-topic-tag">${escapeHtml(q.topic || 'Core Concept')}</span>
                    </div>
                    <div class="exam-q-number">Q${idx + 1}</div>
                </div>
                <div class="exam-q-text">${escapeHtml(q.question)}</div>
                <div class="exam-practice-box">
                    <div class="exam-practice-header">
                        <span><i class="fa-solid fa-pen-to-square"></i> Active Recall Practice Draft</span>
                        <span class="practice-char-count" id="charCount_5m_${idx}">0 words</span>
                    </div>
                    <textarea class="exam-draft-textarea" id="draft_5m_${idx}" placeholder="Write your key points here before revealing model answer..." rows="3" oninput="updateWordCount('draft_5m_${idx}', 'charCount_5m_${idx}')"></textarea>
                </div>
                <div class="exam-action-bar">
                    <button class="btn btn-primary btn-sm" onclick="toggleExamSolution('sol_5m_${idx}', this)"><i class="fa-solid fa-eye"></i> Reveal Model Answer & Rubric</button>
                    <button class="btn btn-outline btn-sm" onclick="teachExamQuestion('${escapeHtml(q.question).replace(/'/g, "\\'")}')"><i class="fa-solid fa-robot"></i> Ask AI Teacher</button>
                </div>
                <div id="sol_5m_${idx}" class="exam-solution-collapse hidden">
                    <div class="exam-rubric-box">
                        <div class="exam-rubric-title"><i class="fa-solid fa-clipboard-list"></i> Marking Scheme Breakdown (5.0 Marks)</div>
                        <ul class="exam-rubric-list">${rubricHtml}</ul>
                    </div>
                    <div class="exam-model-answer-box">
                        <div class="exam-model-title"><i class="fa-solid fa-award"></i> Comprehensive Model Solution</div>
                        <div class="exam-model-text">${renderMarkdownSafely(q.model_answer)}</div>
                    </div>
                </div>
            `;
            container.appendChild(card);
        });
    }

    // 2. Render 10-Mark Case Studies
    if ((filter === 'all' || filter === '10mark') && examPackData.ten_mark_questions.length > 0) {
        if (filter === 'all') {
            const div = document.createElement('div');
            div.className = 'exam-section-divider';
            div.innerHTML = `<div class="exam-section-title"><span class="exam-type-badge badge-10m"><i class="fa-solid fa-trophy"></i> Section B: 10-Mark Comprehensive Case Studies</span></div>`;
            container.appendChild(div);
        }

        examPackData.ten_mark_questions.forEach((q, idx) => {
            const card = document.createElement('div');
            card.className = 'exam-q-card ten-mark-card';
            let partsHtml = (q.parts || []).map(p => `
                <div class="case-part-box">
                    <span class="case-part-badge">Part ${escapeHtml(p.part)} (${p.marks} Marks)</span>
                    <div class="case-part-q">${escapeHtml(p.question)}</div>
                    <div class="case-part-model"><div>${renderMarkdownSafely(p.model_answer)}</div></div>
                </div>
            `).join('');

            card.innerHTML = `
                <div class="exam-q-header">
                    <div class="exam-q-tags">
                        <span class="exam-points-badge badge-10m">🏆 10 MARKS CASE STUDY</span>
                        <span class="exam-topic-tag">${escapeHtml(q.title || 'Architectural Scenario')}</span>
                    </div>
                    <div class="exam-q-number">Case Study ${idx + 1}</div>
                </div>
                <div class="case-scenario-box">
                    <div class="case-scenario-label"><i class="fa-solid fa-building-shield"></i> Enterprise Architectural Scenario:</div>
                    <div class="case-scenario-text">${escapeHtml(q.scenario)}</div>
                </div>
                <div class="exam-action-bar">
                    <button class="btn btn-primary btn-sm" onclick="toggleExamSolution('sol_10m_${idx}', this)"><i class="fa-solid fa-eye"></i> Reveal Full 10-Mark Solution</button>
                    <button class="btn btn-outline btn-sm" onclick="teachExamQuestion('Case Study: ${escapeHtml(q.title).replace(/'/g, "\\'")}')"><i class="fa-solid fa-robot"></i> Ask AI Teacher</button>
                </div>
                <div id="sol_10m_${idx}" class="exam-solution-collapse hidden">
                    <div class="case-parts-container">${partsHtml}</div>
                </div>
            `;
            container.appendChild(card);
        });
    }

    // 3. Render Practice MCQs
    if ((filter === 'all' || filter === 'mcqs') && examPackData.practice_mcqs.length > 0) {
        if (filter === 'all') {
            const div = document.createElement('div');
            div.className = 'exam-section-divider';
            div.innerHTML = `<div class="exam-section-title"><span class="exam-type-badge badge-mcq"><i class="fa-solid fa-list-check"></i> Section C: Interactive Practice MCQs</span></div>`;
            container.appendChild(div);
        }

        examPackData.practice_mcqs.forEach((q, qIdx) => {
            const qCard = document.createElement('div');
            qCard.className = 'quiz-question-card mcq-card';
            qCard.id = `mcqCard_${qIdx}`;

            let optionsHtml = q.options.map((opt, optIdx) => `
                <button class="quiz-option-btn" onclick="checkExamMcqAnswer(${qIdx}, ${optIdx}, ${q.answer_index})">
                    ${String.fromCharCode(65 + optIdx)}. ${escapeHtml(opt)}
                </button>
            `).join('');

            qCard.innerHTML = `
                <div class="exam-q-header" style="margin-bottom: 8px;">
                    <span class="exam-points-badge badge-mcq">🎯 Practice MCQ</span>
                    <span class="exam-q-number">Q${qIdx + 1}</span>
                </div>
                <div class="quiz-q-title">${escapeHtml(q.question)}</div>
                <div class="quiz-options">${optionsHtml}</div>
                <div id="mcqExplanation_${qIdx}" class="quiz-explanation hidden">
                    <div>${renderMarkdownSafely(q.explanation || '')}</div>
                </div>
            `;
            container.appendChild(qCard);
        });
    }
}

function toggleExamSolution(elementId, btn) {
    const el = document.getElementById(elementId);
    if (!el) return;
    const isHidden = el.classList.contains('hidden');
    if (isHidden) {
        el.classList.remove('hidden');
        if (btn) btn.innerHTML = `<i class="fa-solid fa-eye-slash"></i> Hide Solution & Rubric`;
    } else {
        el.classList.add('hidden');
        if (btn) btn.innerHTML = `<i class="fa-solid fa-eye"></i> Reveal Model Answer & Rubric`;
    }
}

function updateWordCount(textareaId, counterId) {
    const ta = document.getElementById(textareaId);
    const counter = document.getElementById(counterId);
    if (!ta || !counter) return;
    const text = ta.value.trim();
    const words = text ? text.split(/\s+/).length : 0;
    counter.textContent = `${words} word${words === 1 ? '' : 's'}`;
}

function teachExamQuestion(questionText) {
    switchTab('tab-chat');
    sendSuggestedQuestion(`Help me master this exam question in depth: "${questionText}". Explain the marking rubric, model answer, and key edge cases in simple terms.`);
}

function checkExamMcqAnswer(qIdx, selectedIdx, correctIdx) {
    const card = document.getElementById(`mcqCard_${qIdx}`);
    if (!card) return;
    const buttons = card.querySelectorAll('.quiz-option-btn');
    const explanation = document.getElementById(`mcqExplanation_${qIdx}`);

    sessionTracker.quizAttempts++;
    const isCorrect = (selectedIdx === correctIdx);
    if (isCorrect) {
        sessionTracker.quizCorrect++;
        sessionTracker.xpEarned += 10;
        sounds.correct();
    } else {
        sounds.again();
    }

    buttons.forEach((btn, idx) => {
        btn.disabled = true;
        if (idx === correctIdx) btn.classList.add('correct');
        else if (idx === selectedIdx) btn.classList.add('incorrect');
    });

    if (explanation) explanation.classList.remove('hidden');
}

// ==========================================================================
// 12. AI CHAT TUTOR (Personas, Feynman Technique & Follow-Up Chips)
// ==========================================================================
function initChat() {
    const sendBtn = document.getElementById('sendChatBtn');
    const input = document.getElementById('chatInput');

    if (input) {
        input.addEventListener('input', () => {
            input.style.height = 'auto';
            input.style.height = Math.min(input.scrollHeight, 160) + 'px';
        });

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSendChat();
            }
        });
    }

    if (sendBtn) {
        sendBtn.addEventListener('click', handleSendChat);
    }
}

function selectTeacherPersona(mode) {
    selectedTeacherPersona = mode;
    const cards = document.querySelectorAll('.persona-card');
    cards.forEach(c => {
        if (c.getAttribute('data-mode') === mode) {
            c.classList.add('active');
            c.setAttribute('aria-checked', 'true');
        } else {
            c.classList.remove('active');
            c.setAttribute('aria-checked', 'false');
        }
    });

    const nameMap = {
        'socratic': 'Socratic Sage',
        'eli5': 'ELI5 Buddy',
        'quiz_me': 'Strict Examiner',
        'notes_deepdive': 'Notes Detective'
    };

    const activeName = document.getElementById('activeTeacherName');
    const modeTag = document.getElementById('currentModeTag');
    if (activeName) activeName.textContent = nameMap[mode] || 'AI Teacher';
    if (modeTag) modeTag.innerHTML = `<i class="fa-solid fa-wand-magic-sparkles"></i> ${escapeHtml(nameMap[mode] || 'AI Teacher')}`;
}

function switchChatSubView(view) {
    const chatBtn = document.getElementById('viewChatModeBtn');
    const feynmanBtn = document.getElementById('viewFeynmanModeBtn');
    const chatSec = document.getElementById('chatStreamContainer');
    const feynmanSec = document.getElementById('feynmanContainer');

    if (view === 'feynman') {
        if (feynmanBtn) feynmanBtn.className = 'btn btn-primary btn-sm active';
        if (chatBtn) chatBtn.className = 'btn btn-outline btn-sm';
        if (feynmanSec) feynmanSec.classList.remove('hidden');
        if (chatSec) chatSec.classList.add('hidden');
    } else {
        if (chatBtn) chatBtn.className = 'btn btn-primary btn-sm active';
        if (feynmanBtn) feynmanBtn.className = 'btn btn-outline btn-sm';
        if (chatSec) chatSec.classList.remove('hidden');
        if (feynmanSec) feynmanSec.classList.add('hidden');
    }
}

async function submitFeynmanExplanation() {
    hideError();
    const conceptInput = document.getElementById('feynmanConceptInput');
    const expInput = document.getElementById('feynmanExplanationInput');
    const submitBtn = document.getElementById('feynmanSubmitBtn');

    if (!conceptInput || !expInput) return;
    const concept = conceptInput.value.trim();
    const explanation = expInput.value.trim();

    if (!concept || !explanation) {
        showError('Please enter both the concept name and your explanation.');
        return;
    }

    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Evaluating Clarity...`;
    }

    try {
        const res = await fetch('/api/study/feynman', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                concept: concept,
                explanation: explanation,
                api_key: getApiKey()
            })
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Feynman evaluation failed');
        }

        const data = await res.json();
        const resultBox = document.getElementById('feynmanResultBox');
        if (resultBox) resultBox.classList.remove('hidden');

        const scoreText = document.getElementById('feynmanScoreText');
        if (scoreText) scoreText.textContent = data.clarity_score || 80;

        const scoreTitle = document.getElementById('feynmanScoreTitle');
        if (scoreTitle) {
            const score = data.clarity_score || 80;
            scoreTitle.textContent = score >= 85 ? 'Mastery Unlocked! 🏆' : (score >= 70 ? 'Clear & Solid Explanation 👍' : 'Needs Simplification 📚');
        }

        const mentor = document.getElementById('feynmanMentorFeedback');
        if (mentor) mentor.textContent = `"${data.mentor_feedback || 'Great start. Keep refining the core mechanism!'}"`;

        const xpBadge = document.getElementById('feynmanXpAwardedBadge');
        if (xpBadge) xpBadge.textContent = `+${data.xp_awarded || 50} XP Awarded`;

        // Populate lists
        const strengthsList = document.getElementById('feynmanStrengthsList');
        if (strengthsList) {
            strengthsList.innerHTML = (data.strengths || []).map(s => `<li>${escapeHtml(s)}</li>`).join('');
        }

        const missingList = document.getElementById('feynmanMissingList');
        if (missingList) {
            missingList.innerHTML = (data.missing_elements || []).map(m => `<li>${escapeHtml(m)}</li>`).join('');
        }

        const misBox = document.getElementById('feynmanMisconceptionsBox');
        const misList = document.getElementById('feynmanMisconceptionsList');
        if (misBox && misList) {
            if (data.misconceptions && data.misconceptions.length > 0) {
                misBox.classList.remove('hidden');
                misList.innerHTML = data.misconceptions.map(m => `<li>${escapeHtml(m)}</li>`).join('');
            } else {
                misBox.classList.add('hidden');
            }
        }

        const analogyText = document.getElementById('feynmanAnalogyText');
        if (analogyText) analogyText.textContent = data.simplified_analogy || '';

        sounds.fanfare();
        triggerConfetti();

        sessionTracker.xpEarned += (data.xp_awarded || 50);
        await loadTodaysMission();

    } catch (err) {
        showError('Feynman evaluation error: ' + err.message);
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = `<i class="fa-solid fa-paper-plane"></i> Evaluate Explanation (+XP)`;
        }
    }
}

function updateChatSuggestions(slides) {
    const chipsContainer = document.getElementById('claudeChipsScroll');
    if (!chipsContainer) return;

    if (!slides || slides.length === 0) {
        chipsContainer.innerHTML = `
            <button class="claude-chip" onclick="sendSuggestedQuestion('Summarize the big picture and key takeaways across the entire presentation.')">
                <span>💡 Master Takeaways & Big Picture</span>
            </button>
            <button class="claude-chip" onclick="sendSuggestedQuestion('Explain the core concepts and mechanisms using simple everyday analogies.')">
                <span>🌟 Intuitive Real-World Analogies</span>
            </button>
            <button class="claude-chip" onclick="sendSuggestedQuestion('What are the most crucial presenter notes and instructor test hints?')">
                <span>📌 Presenter Notes & Test Clues</span>
            </button>
            <button class="claude-chip" onclick="sendSuggestedQuestion('Quiz me with 3 challenging conceptual questions to test my recall.')">
                <span>🎯 Socratic Recall Challenge</span>
            </button>
        `;
        return;
    }

    const chips = [];
    chips.push({ text: 'Summarize the big picture and key takeaways across the entire presentation.', label: '💡 Master Takeaways & Overview' });

    const candidateSlides = slides.filter(s => s.title && s.title.trim().length > 3 && !s.title.toLowerCase().startsWith('slide '));
    const samplePool = candidateSlides.length > 0 ? candidateSlides : slides;

    samplePool.slice(0, 3).forEach(s => {
        const sNum = s.slide_number || 1;
        const cleanTitle = s.title.replace(/["']/g, '');
        chips.push({
            text: `Teach me Slide ${sNum}: ${cleanTitle} step-by-step with an everyday analogy.`,
            label: `📖 Slide ${sNum}: ${cleanTitle.length > 25 ? cleanTitle.slice(0, 22) + '...' : cleanTitle}`
        });
    });

    chipsContainer.innerHTML = chips.map(c => `
        <button class="claude-chip" onclick="sendSuggestedQuestion('${escapeHtml(c.text).replace(/'/g, "\\'")}')">
            <span>${escapeHtml(c.label)}</span>
        </button>
    `).join('');
}

function sendSuggestedQuestion(qText) {
    const input = document.getElementById('chatInput');
    if (!input) return;
    input.value = qText;
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 160) + 'px';
    handleSendChat();
}

async function handleSendChat() {
    hideError();
    const input = document.getElementById('chatInput');
    if (!input) return;
    const text = input.value.trim();
    if (!text) return;

    input.value = '';
    input.style.height = 'auto';

    appendChatMessage('user', text);
    chatHistory.push({ role: 'user', content: text });

    const typingIndicator = document.getElementById('chatTypingIndicator');
    if (typingIndicator) typingIndicator.classList.remove('hidden');

    try {
        const res = await fetch('/api/study/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: text,
                teacher_mode: selectedTeacherPersona,
                chat_history: chatHistory,
                api_key: getApiKey()
            })
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Chat request failed');
        }

        const data = await res.json();
        if (typingIndicator) typingIndicator.classList.add('hidden');

        const reply = data.reply || 'Could not generate a response.';
        appendChatMessage('ai', reply);
        chatHistory.push({ role: 'assistant', content: reply });

        sessionTracker.xpEarned += 10;

        // Render follow-up chips
        renderFollowUpChips(data.follow_up_chips || [
            "Could you give an everyday analogy for that?",
            "How would this appear on an exam?",
            "What common mistake do students make here?"
        ]);

        if (data.session_memory) {
            updateSessionMemoryUI(data.session_memory);
        }

    } catch (err) {
        if (typingIndicator) typingIndicator.classList.add('hidden');
        showError('Chat error: ' + err.message);
        appendChatMessage('ai', '⚠️ **Error:** ' + err.message);
    }
}

function renderFollowUpChips(chips) {
    const container = document.getElementById('chatFollowUpChips');
    if (!container) return;
    if (!chips || chips.length === 0) {
        container.classList.add('hidden');
        return;
    }

    container.innerHTML = chips.map(c => `
        <button class="follow-up-chip" onclick="sendSuggestedQuestion('${escapeHtml(c).replace(/'/g, "\\'")}')">
            <span>💡 ${escapeHtml(c)}</span>
        </button>
    `).join('');
    container.classList.remove('hidden');
}

function appendChatMessage(sender, text) {
    const container = document.getElementById('chatMessages');
    if (!container) return;
    const msgDiv = document.createElement('div');
    const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    if (sender === 'user') {
        msgDiv.className = 'claude-msg claude-msg-user';
        msgDiv.innerHTML = `<div class="claude-msg-body">${escapeHtml(text).replace(/\n/g, '<br/>')}</div>`;
    } else {
        msgDiv.className = 'claude-msg claude-msg-ai';
        const renderedHtml = renderMarkdownSafely(text);
        const safeTextForAudio = escapeHtml(text).replace(/[`\\]/g, '');

        msgDiv.innerHTML = `
            <div class="claude-msg-avatar"><i class="fa-solid fa-wand-magic-sparkles"></i></div>
            <div class="claude-msg-body">
                <div class="claude-msg-meta">
                    <span class="claude-msg-author">${escapeHtml(document.getElementById('activeTeacherName')?.textContent || 'AI Teacher')}</span>
                    <span class="claude-msg-badge">Tutor</span>
                </div>
                <div class="claude-msg-content markdown-body">${renderedHtml}</div>
                <div class="claude-msg-actions">
                    <button class="claude-action-btn" onclick="speakText(\`${safeTextForAudio}\`)" title="Listen"><i class="fa-solid fa-volume-high"></i> Listen</button>
                    <button class="claude-action-btn" onclick="copyMessageText(this)" title="Copy"><i class="fa-regular fa-copy"></i> Copy</button>
                    <span class="claude-msg-time">${timeStr}</span>
                </div>
            </div>
        `;
    }

    container.appendChild(msgDiv);
    if (window.hljs) {
        msgDiv.querySelectorAll('pre code').forEach(block => window.hljs.highlightElement(block));
    }
    container.scrollTop = container.scrollHeight;
}

function renderMarkdownSafely(text) {
    if (window.marked && typeof window.marked.parse === 'function') {
        try {
            return window.marked.parse(text);
        } catch (e) {}
    }
    return escapeHtml(text).replace(/\n/g, '<br/>');
}

function copyMessageText(btn) {
    const parentMsg = btn.closest('.claude-msg-body');
    if (!parentMsg) return;
    const contentEl = parentMsg.querySelector('.claude-msg-content');
    if (!contentEl) return;
    const text = contentEl.innerText || contentEl.textContent;
    navigator.clipboard.writeText(text).then(() => {
        const origHtml = btn.innerHTML;
        btn.innerHTML = `<i class="fa-solid fa-check" style="color: var(--accent-emerald);"></i> Copied!`;
        setTimeout(() => { btn.innerHTML = origHtml; }, 2000);
    });
}

function clearChatHistory() {
    chatHistory = [];
    try { fetch('/api/study/chat/memory', { method: 'DELETE' }); } catch (e) {}
    const container = document.getElementById('chatMessages');
    if (container) {
        container.innerHTML = `
            <div class="claude-msg claude-msg-ai">
                <div class="claude-msg-avatar"><i class="fa-solid fa-wand-magic-sparkles"></i></div>
                <div class="claude-msg-body">
                    <div class="claude-msg-meta"><span class="claude-msg-author">AI Tutor</span></div>
                    <div class="claude-msg-content markdown-body">Chat memory reset. What concept would you like to explore?</div>
                </div>
            </div>
        `;
    }
}

function updateSessionMemoryUI(sessionMemory) {
    const memBar = document.getElementById('sessionMemoryBar');
    const topicsEl = document.getElementById('sessionMemoryTopics');
    if (!memBar || !topicsEl || !sessionMemory) return;
    const topics = sessionMemory.topics_explored || sessionMemory.last_topic || '';
    if (topics) {
        topicsEl.textContent = topics;
        memBar.classList.remove('hidden');
    }
}

function clearSessionMemoryOnly() {
    try {
        fetch('/api/study/chat/memory', { method: 'DELETE' });
        const memBar = document.getElementById('sessionMemoryBar');
        if (memBar) memBar.classList.add('hidden');
    } catch (e) {}
}

// ==========================================================================
// 13. QUIZ MASTER & "BOSS BATTLE" MODE
// ==========================================================================
let quizMasterState = {
    examTitle: '',
    questions: [],
    currentIndex: 0,
    userAnswers: {},
    flagged: {},
    startTime: null,
    timerInterval: null,
    timeLimitSeconds: 300,
    remainingSeconds: 300,
    lives: 3,
    bossMaxHp: 5,
    bossCurrentHp: 5,
    comboMultiplier: 1,
    questionTimer: 30,
    questionTimerInterval: null,
    missedQuestions: []
};

function setQuizMasterMode(mode) {
    quizMasterMode = mode;
    const classicBtn = document.getElementById('qmModeClassicBtn');
    const bossBtn = document.getElementById('qmModeBossBtn');
    const startBtnText = document.getElementById('startExamBtnText');

    if (mode === 'boss') {
        if (bossBtn) bossBtn.classList.add('active');
        if (classicBtn) classicBtn.classList.remove('active');
        if (startBtnText) startBtnText.textContent = '⚔️ Enter Boss Battle Arena';
    } else {
        if (classicBtn) classicBtn.classList.add('active');
        if (bossBtn) bossBtn.classList.remove('active');
        if (startBtnText) startBtnText.textContent = 'Start Timed Exam';
    }
}

async function startQuizMasterExam(customQuestions = null) {
    hideError();
    const diff = document.getElementById('qmDifficulty').value;
    const count = parseInt(document.getElementById('qmCount').value, 10);
    const topic = document.getElementById('qmTopic').value.trim();

    const setupCard = document.getElementById('qmSetupCard');
    const examCard = document.getElementById('qmExamCard');
    const scorecardCard = document.getElementById('qmScorecardCard');
    const historyCard = document.getElementById('qmHistoryCard');

    try {
        let questions = customQuestions;
        let examTitle = 'Mock Exam';

        if (!questions) {
            const res = await fetch('/api/quizmaster/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    difficulty: diff,
                    question_count: count,
                    topic: topic || null,
                    api_key: getApiKey()
                })
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Failed to generate exam');
            }

            const data = await res.json();
            questions = data.questions || [];
            examTitle = data.exam_title;
        }

        if (questions.length === 0) {
            throw new Error('No exam questions could be generated from document.');
        }

        quizMasterState = {
            examTitle: examTitle,
            questions: questions,
            currentIndex: 0,
            userAnswers: {},
            flagged: {},
            startTime: Date.now(),
            timerInterval: null,
            timeLimitSeconds: questions.length * 60,
            remainingSeconds: questions.length * 60,
            lives: 3,
            bossMaxHp: questions.length,
            bossCurrentHp: questions.length,
            comboMultiplier: 1,
            questionTimer: 30,
            questionTimerInterval: null,
            missedQuestions: []
        };

        document.getElementById('qmExamTitle').textContent = examTitle;
        setupCard.classList.add('hidden');
        scorecardCard.classList.add('hidden');
        historyCard.classList.add('hidden');
        examCard.classList.remove('hidden');

        // Init Boss Arena if boss mode
        const bossArena = document.getElementById('qmBossArena');
        if (quizMasterMode === 'boss') {
            if (bossArena) bossArena.classList.remove('hidden');
            updateBossArenaHUD();
            startQuestionTimer();
        } else if (bossArena) {
            bossArena.classList.add('hidden');
        }

        startQuizMasterTimer();
        renderQuizMasterNavPills();
        renderQuizMasterCurrentQuestion();

    } catch (err) {
        showError('Quiz Master Error: ' + err.message);
    }
}

function updateBossArenaHUD() {
    const hearts = ['🖤🖤🖤', '❤️🖤🖤', '❤️❤️🖤', '❤️❤️❤️'];
    const livesIcons = document.getElementById('bossLivesIcons');
    if (livesIcons) livesIcons.textContent = hearts[Math.max(0, Math.min(3, quizMasterState.lives))];

    const hpPercent = Math.round((quizMasterState.bossCurrentHp / quizMasterState.bossMaxHp) * 100);
    const healthFill = document.getElementById('bossHealthBarFill');
    if (healthFill) healthFill.style.width = `${Math.max(0, hpPercent)}%`;

    const healthText = document.getElementById('bossHealthPercent');
    if (healthText) healthText.textContent = `${Math.max(0, hpPercent)}% HP`;

    const multBadge = document.getElementById('bossMultiplierBadge');
    if (multBadge) multBadge.textContent = `⚡ ${quizMasterState.comboMultiplier}x Multiplier`;
}

function startQuestionTimer() {
    if (quizMasterState.questionTimerInterval) clearInterval(quizMasterState.questionTimerInterval);
    quizMasterState.questionTimer = 30;

    const timerText = document.getElementById('bossQuestionTimerText');
    const timerFill = document.getElementById('bossTimerFill');

    function update() {
        if (timerText) timerText.textContent = `${quizMasterState.questionTimer}s`;
        const pct = Math.round((quizMasterState.questionTimer / 30) * 100);
        if (timerFill) timerFill.setAttribute('stroke-dasharray', `${pct}, 100`);
    }
    update();

    quizMasterState.questionTimerInterval = setInterval(() => {
        quizMasterState.questionTimer--;
        update();
        if (quizMasterState.questionTimer <= 0) {
            clearInterval(quizMasterState.questionTimerInterval);
            sounds.again();
            quizMasterState.lives--;
            updateBossArenaHUD();
            if (quizMasterState.lives <= 0) {
                alert('💔 Out of lives! The Boss defeated you. Submitting your score...');
                submitQuizMasterExam();
            } else {
                nextQuizMasterQuestion();
            }
        }
    }, 1000);
}

function startQuizMasterTimer() {
    if (quizMasterState.timerInterval) clearInterval(quizMasterState.timerInterval);
    const timerDisplay = document.getElementById('qmTimerDisplay');
    const timerWrapper = document.getElementById('qmTimerWrapper');

    function update() {
        const mins = Math.floor(Math.max(0, quizMasterState.remainingSeconds) / 60);
        const secs = Math.max(0, quizMasterState.remainingSeconds) % 60;
        if (timerDisplay) timerDisplay.textContent = `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
        if (timerWrapper) {
            if (quizMasterState.remainingSeconds <= 60) timerWrapper.classList.add('warning');
            else timerWrapper.classList.remove('warning');
        }
    }
    update();

    quizMasterState.timerInterval = setInterval(() => {
        quizMasterState.remainingSeconds--;
        update();
        if (quizMasterState.remainingSeconds <= 0) {
            clearInterval(quizMasterState.timerInterval);
            alert('⏱️ Time is up! Submitting exam.');
            submitQuizMasterExam();
        }
    }, 1000);
}

function renderQuizMasterNavPills() {
    const container = document.getElementById('qmNavPills');
    if (!container) return;
    container.innerHTML = '';

    quizMasterState.questions.forEach((q, idx) => {
        const pill = document.createElement('div');
        let classes = 'qm-pill';
        if (idx === quizMasterState.currentIndex) classes += ' active';
        if (quizMasterState.userAnswers.hasOwnProperty(idx)) classes += ' answered';
        if (quizMasterState.flagged[idx]) classes += ' flagged';

        pill.className = classes;
        pill.textContent = idx + 1;
        pill.onclick = () => {
            quizMasterState.currentIndex = idx;
            renderQuizMasterNavPills();
            renderQuizMasterCurrentQuestion();
        };
        container.appendChild(pill);
    });
}

function renderQuizMasterCurrentQuestion() {
    const idx = quizMasterState.currentIndex;
    const q = quizMasterState.questions[idx];
    const total = quizMasterState.questions.length;

    const prog = document.getElementById('qmQuestionProgress');
    if (prog) prog.textContent = `Question ${idx + 1} of ${total}`;

    const container = document.getElementById('qmActiveQuestionContainer');
    let optionsHtml = '';

    q.options.forEach((opt, optIdx) => {
        const isSelected = quizMasterState.userAnswers[idx] === optIdx;
        const selectedClass = isSelected ? 'correct' : '';
        optionsHtml += `
            <button class="quiz-option-btn ${selectedClass}" onclick="selectQuizMasterOption(${optIdx})">
                ${String.fromCharCode(65 + optIdx)}. ${escapeHtml(opt)}
            </button>
        `;
    });

    const diffBadge = q.difficulty ? `<span class="slide-num-badge" style="background: var(--secondary); margin-right: 8px;">${q.difficulty}</span>` : '';
    const topicBadge = q.topic ? `<span class="slide-num-badge" style="background: var(--text-muted);">${escapeHtml(q.topic)}</span>` : '';

    container.innerHTML = `
        <div style="margin-bottom: 12px;">${diffBadge}${topicBadge}</div>
        <div class="quiz-q-title">Q${idx + 1}. ${escapeHtml(q.question)}</div>
        <div class="quiz-options">${optionsHtml}</div>
    `;

    document.getElementById('qmPrevBtn').disabled = (idx === 0);
    const flagBtn = document.getElementById('qmFlagBtn');
    if (flagBtn) {
        flagBtn.innerHTML = quizMasterState.flagged[idx] ? `<i class="fa-solid fa-bookmark"></i> Unflag` : `<i class="fa-regular fa-bookmark"></i> Flag Question`;
    }

    const nextBtn = document.getElementById('qmNextBtn');
    const submitBtn = document.getElementById('qmSubmitBtn');

    if (idx === total - 1) {
        nextBtn.classList.add('hidden');
        submitBtn.classList.remove('hidden');
    } else {
        nextBtn.classList.remove('hidden');
        submitBtn.classList.add('hidden');
    }
}

function selectQuizMasterOption(optIdx) {
    const idx = quizMasterState.currentIndex;
    const q = quizMasterState.questions[idx];
    quizMasterState.userAnswers[idx] = optIdx;

    if (quizMasterMode === 'boss') {
        const isCorrect = (optIdx === q.answer_index);
        if (isCorrect) {
            quizMasterState.comboMultiplier++;
            quizMasterState.bossCurrentHp = Math.max(0, quizMasterState.bossCurrentHp - 1);
            sounds.bossHit();
        } else {
            quizMasterState.comboMultiplier = 1;
            quizMasterState.lives--;
            sounds.again();
        }
        updateBossArenaHUD();

        if (quizMasterState.lives <= 0) {
            alert('💔 All lives lost! The Boss defeated you.');
            submitQuizMasterExam();
            return;
        }
    }

    renderQuizMasterNavPills();
    renderQuizMasterCurrentQuestion();
}

function toggleFlagQuizMasterQuestion() {
    const idx = quizMasterState.currentIndex;
    quizMasterState.flagged[idx] = !quizMasterState.flagged[idx];
    renderQuizMasterNavPills();
    renderQuizMasterCurrentQuestion();
}

function prevQuizMasterQuestion() {
    if (quizMasterState.currentIndex > 0) {
        quizMasterState.currentIndex--;
        if (quizMasterMode === 'boss') startQuestionTimer();
        renderQuizMasterNavPills();
        renderQuizMasterCurrentQuestion();
    }
}

function nextQuizMasterQuestion() {
    if (quizMasterState.currentIndex < quizMasterState.questions.length - 1) {
        quizMasterState.currentIndex++;
        if (quizMasterMode === 'boss') startQuestionTimer();
        renderQuizMasterNavPills();
        renderQuizMasterCurrentQuestion();
    }
}

async function submitQuizMasterExam() {
    if (quizMasterState.timerInterval) clearInterval(quizMasterState.timerInterval);
    if (quizMasterState.questionTimerInterval) clearInterval(quizMasterState.questionTimerInterval);

    const timeSpent = Math.max(1, Math.round((Date.now() - quizMasterState.startTime) / 1000));
    let correctCount = 0;
    const details = [];
    const missed = [];

    quizMasterState.questions.forEach((q, idx) => {
        const userOpt = quizMasterState.userAnswers[idx];
        const isCorrect = (userOpt === q.answer_index);
        if (isCorrect) correctCount++;
        else missed.push(q);

        details.push({
            question_id: q.id,
            question: q.question,
            user_option: userOpt !== undefined ? q.options[userOpt] : "No answer selected",
            correct_option: q.options[q.answer_index],
            is_correct: isCorrect,
            explanation: q.explanation
        });
    });

    quizMasterState.missedQuestions = missed;
    const total = quizMasterState.questions.length;
    const percent = Math.round((correctCount / total) * 100);

    sessionTracker.quizAttempts += total;
    sessionTracker.quizCorrect += correctCount;
    sessionTracker.xpEarned += (50 + correctCount * 5);

    try {
        await fetch('/api/quizmaster/submit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                exam_title: quizMasterState.examTitle.slice(0, 100),
                score: correctCount,
                total_questions: total,
                time_spent_seconds: timeSpent,
                details: details.slice(0, 50)
            })
        });
    } catch (e) {
        console.error('Submit API error:', e.message);
    }

    // Render Scorecard
    document.getElementById('qmExamCard').classList.add('hidden');
    document.getElementById('qmScorecardCard').classList.remove('hidden');

    const gaugePath = document.getElementById('qmGaugePath');
    const percentText = document.getElementById('qmScorePercentText');
    const gradeHeading = document.getElementById('qmScoreGrade');
    const summaryText = document.getElementById('qmScoreSummaryText');

    if (gaugePath) gaugePath.setAttribute('stroke-dasharray', `${percent}, 100`);
    if (percentText) percentText.textContent = `${percent}%`;

    let grade = 'Mastery Achieved! 🏆';
    if (percent < 50) grade = 'Needs Revision 📚';
    else if (percent < 80) grade = 'Good Progress! 👍';
    if (gradeHeading) gradeHeading.textContent = grade;

    const mins = Math.floor(timeSpent / 60);
    const secs = timeSpent % 60;
    if (summaryText) summaryText.textContent = `You scored ${correctCount} out of ${total} correctly in ${mins}m ${secs}s.`;

    // Retry Missed Questions button visibility
    const retryBtn = document.getElementById('qmRetryMissedBtn');
    if (retryBtn) {
        if (missed.length > 0) retryBtn.classList.remove('hidden');
        else retryBtn.classList.add('hidden');
    }

    // Review Breakdown
    const reviewContainer = document.getElementById('qmReviewContainer');
    let reviewHtml = '';

    details.forEach((d, idx) => {
        const badge = d.is_correct ? `<span class="badge badge-active">✔ Correct</span>` : `<span class="badge badge-fallback" style="background:#fee2e2; color:#b91c1c;">✘ Incorrect</span>`;
        reviewHtml += `
            <div class="quiz-question-card">
                <div class="flex-between" style="margin-bottom: 8px;">
                    <div class="quiz-q-title" style="margin: 0;">Q${idx + 1}. ${escapeHtml(d.question)}</div>
                    ${badge}
                </div>
                <p style="font-size: 13px; margin-bottom: 4px;"><strong>Your Answer:</strong> <span style="color: ${d.is_correct ? 'var(--accent-emerald)' : 'var(--danger)'};">${escapeHtml(d.user_option)}</span></p>
                ${!d.is_correct ? `<p style="font-size: 13px; margin-bottom: 4px;"><strong>Correct Answer:</strong> <span style="color: var(--accent-emerald);">${escapeHtml(d.correct_option)}</span></p>` : ''}
                <div class="quiz-explanation" style="margin-top: 8px;">
                    <strong>Teacher Explanation:</strong> ${escapeHtml(d.explanation)}
                </div>
                ${!d.is_correct ? `
                    <div style="margin-top: 10px;">
                        <button class="btn btn-outline btn-sm" onclick="explainMissedQuestion('${escapeHtml(d.question).replace(/'/g, "\\'")}', '${escapeHtml(d.user_option).replace(/'/g, "\\'")}', '${escapeHtml(d.correct_option).replace(/'/g, "\\'")}')">
                            <i class="fa-solid fa-graduation-cap"></i> 💡 Explain this to me (AI Tutor)
                        </button>
                    </div>
                ` : ''}
            </div>
        `;
    });

    if (reviewContainer) reviewContainer.innerHTML = reviewHtml;

    if (percent >= 80) {
        sounds.fanfare();
        triggerConfetti();
    }

    loadTodaysMission();
    loadMasteryMap();
}

function explainMissedQuestion(question, userChoice, correctChoice) {
    switchTab('tab-chat');
    selectTeacherPersona('socratic');
    const prompt = `I missed this question on the exam: "${question}". I answered "${userChoice}", but the correct answer is "${correctChoice}". Can you explain why my choice was incorrect, the underlying mechanism, and how to avoid this trap on future exams?`;
    sendSuggestedQuestion(prompt);
}

function retryMissedQuestions() {
    if (!quizMasterState.missedQuestions || quizMasterState.missedQuestions.length === 0) return;
    startQuizMasterExam(quizMasterState.missedQuestions);
}

function resetQuizMasterSetup() {
    if (quizMasterState.timerInterval) clearInterval(quizMasterState.timerInterval);
    if (quizMasterState.questionTimerInterval) clearInterval(quizMasterState.questionTimerInterval);
    document.getElementById('qmExamCard').classList.add('hidden');
    document.getElementById('qmScorecardCard').classList.add('hidden');
    document.getElementById('qmHistoryCard').classList.add('hidden');
    document.getElementById('qmSetupCard').classList.remove('hidden');
}

async function loadQuizMasterHistory() {
    hideError();
    const setupCard = document.getElementById('qmSetupCard');
    const examCard = document.getElementById('qmExamCard');
    const scorecardCard = document.getElementById('qmScorecardCard');
    const historyCard = document.getElementById('qmHistoryCard');
    const container = document.getElementById('qmHistoryTableContainer');

    setupCard.classList.add('hidden');
    examCard.classList.add('hidden');
    scorecardCard.classList.add('hidden');
    historyCard.classList.remove('hidden');

    container.innerHTML = `<div class="loading-overlay"><div class="spinner"></div><p>Loading score history...</p></div>`;

    try {
        const res = await fetch('/api/quizmaster/history');
        if (!res.ok) throw new Error('Failed to fetch score history');
        const data = await res.json();
        const history = data.history || [];

        if (history.length === 0) {
            container.innerHTML = `<p class="placeholder-state">No past exam attempts recorded yet for this session.</p>`;
            return;
        }

        let html = `
            <table class="qm-table">
                <thead>
                    <tr>
                        <th>Date & Time</th>
                        <th>Exam Title</th>
                        <th>Score</th>
                        <th>Percentage</th>
                        <th>Time Spent</th>
                    </tr>
                </thead>
                <tbody>
        `;

        history.forEach(h => {
            const mins = Math.floor(h.time_spent_seconds / 60);
            const secs = h.time_spent_seconds % 60;
            const timeFmt = `${mins}m ${secs}s`;
            const badgeClass = h.percentage >= 80 ? 'badge-active' : 'badge-fallback';

            html += `
                <tr>
                    <td>${escapeHtml(h.created_at)}</td>
                    <td><strong>${escapeHtml(h.exam_title)}</strong></td>
                    <td>${h.score} / ${h.total_questions}</td>
                    <td><span class="badge ${badgeClass}">${h.percentage}%</span></td>
                    <td>${timeFmt}</td>
                </tr>
            `;
        });

        html += `</tbody></table>`;
        container.innerHTML = html;

    } catch (err) {
        showError('History error: ' + err.message);
        container.innerHTML = `<p style="color: var(--danger);">${escapeHtml(err.message)}</p>`;
    }
}

function closeQuizMasterHistory() {
    document.getElementById('qmHistoryCard').classList.add('hidden');
    document.getElementById('qmSetupCard').classList.remove('hidden');
}

// ==========================================================================
// 14. END STUDY SESSION MODAL & SUMMARY METRICS
// ==========================================================================
function initSessionFinish() {
    const finishBtn = document.getElementById('finishSessionBtn');
    if (finishBtn) {
        finishBtn.addEventListener('click', openSessionSummaryModal);
    }
}

async function openSessionSummaryModal() {
    const modal = document.getElementById('sessionSummaryModal');
    if (!modal) return;

    const elapsedMs = Date.now() - sessionTracker.startTime;
    const mins = Math.max(1, Math.round(elapsedMs / 60000));

    const timeEl = document.getElementById('summaryTimeSpent');
    if (timeEl) timeEl.textContent = `${mins}m`;

    const xpEl = document.getElementById('summaryXpEarned');
    if (xpEl) xpEl.textContent = `+${sessionTracker.xpEarned} XP`;

    const cardsEl = document.getElementById('summaryCardsReviewed');
    if (cardsEl) cardsEl.textContent = sessionTracker.cardsReviewed;

    const accEl = document.getElementById('summaryQuizAccuracy');
    if (accEl) {
        const accuracy = sessionTracker.quizAttempts > 0
            ? Math.round((sessionTracker.quizCorrect / sessionTracker.quizAttempts) * 100)
            : 100;
        accEl.textContent = `${accuracy}%`;
    }

    // Pull weakest spots from mastery
    try {
        const mRes = await fetch('/api/study/mastery');
        if (mRes.ok) {
            const mData = await mRes.json();
            const weakList = document.getElementById('summaryWeakestList');
            if (weakList) {
                if (mData.weak_spots && mData.weak_spots.length > 0) {
                    weakList.innerHTML = mData.weak_spots.slice(0, 3).map(w => `
                        <li><i class="fa-solid fa-crosshairs text-danger"></i> <strong>Slide ${w.slide_number}:</strong> ${escapeHtml(w.title)} (${w.mastery_percent}% mastery)</li>
                    `).join('');
                } else {
                    weakList.innerHTML = `<li><i class="fa-solid fa-circle-check text-success"></i> All slides currently above mastery threshold!</li>`;
                }
            }
        }
    } catch (e) {}

    sounds.fanfare();
    modal.classList.remove('hidden');
}

function closeSessionSummaryModal() {
    const modal = document.getElementById('sessionSummaryModal');
    if (modal) modal.classList.add('hidden');
}

// Helper: Escape HTML
function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
