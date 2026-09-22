// State
let presentationData = null;
let currentFlashcardIndex = 0;
let flashcardsList = [];
let quizList = [];
let chatHistory = [];

document.addEventListener('DOMContentLoaded', () => {
    initApiKey();
    initFileUpload();
    initSampleDemo();
    initExportText();
    initSearch();
    initTabs();
    initChat();
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

// Session restoration on page load/refresh
async function checkCurrentSession() {
    try {
        const res = await fetch('/api/current');
        const data = await res.json();
        if (data.loaded) {
            presentationData = data;
            renderSlides(data.slides);
            document.getElementById('loadedFileName').textContent = data.filename;
            document.getElementById('slideCountBadge').textContent = `${data.total_slides} Slides Extracted`;
            document.getElementById('tabSlideCount').textContent = data.total_slides;

            document.getElementById('uploadSection').classList.add('hidden');
            document.getElementById('workspaceSection').classList.remove('hidden');
        }
    } catch (err) {
        console.log('Session check:', err.message);
    }
}

// API Key Logic
function initApiKey() {
    const savedKey = localStorage.getItem('gemini_api_key');
    const input = document.getElementById('apiKeyInput');
    const saveBtn = document.getElementById('saveKeyBtn');
    const badge = document.getElementById('aiStatusBadge');
    const statusText = document.getElementById('aiStatusText');

    if (savedKey) {
        input.value = savedKey;
        updateBadge(true);
    }

    saveBtn.addEventListener('click', () => {
        const val = input.value.trim();
        if (val) {
            localStorage.setItem('gemini_api_key', val);
            updateBadge(true);
            alert('Gemini API Key saved for this session!');
        } else {
            localStorage.removeItem('gemini_api_key');
            updateBadge(false);
            alert('API Key cleared. Switched to smart local mode.');
        }
    });

    function updateBadge(hasKey) {
        if (hasKey) {
            badge.className = 'badge badge-active';
            statusText.textContent = 'Gemini AI Active';
            badge.title = 'Gemini AI model is active.';
        } else {
            badge.className = 'badge badge-fallback';
            statusText.textContent = 'Smart Local Mode';
            badge.title = 'Enter API key to unlock full Gemini generative AI features.';
        }
    }
}

function getApiKey() {
    return localStorage.getItem('gemini_api_key') || null;
}

// Sample Demo Handler
function initSampleDemo() {
    const btn1 = document.getElementById('sampleDemoBtn');
    const btn2 = document.getElementById('heroSampleBtn');

    [btn1, btn2].forEach(btn => {
        if (btn) {
            btn.addEventListener('click', loadSampleDemo);
        }
    });
}

async function loadSampleDemo() {
    hideError();
    const uploadSection = document.getElementById('uploadSection');
    const loadingOverlay = document.getElementById('loadingOverlay');
    const workspaceSection = document.getElementById('workspaceSection');

    uploadSection.classList.add('hidden');
    loadingOverlay.classList.remove('hidden');

    try {
        const response = await fetch('/api/sample', { method: 'POST' });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Failed to load sample demo');
        }

        const data = await response.json();
        presentationData = data;

        renderSlides(data.slides);
        document.getElementById('loadedFileName').textContent = data.filename;
        document.getElementById('slideCountBadge').textContent = `${data.total_slides} Slides Extracted`;
        document.getElementById('tabSlideCount').textContent = data.total_slides;

        loadingOverlay.classList.add('hidden');
        workspaceSection.classList.remove('hidden');

    } catch (err) {
        showError('Error loading sample presentation: ' + err.message);
        loadingOverlay.classList.add('hidden');
        uploadSection.classList.remove('hidden');
    }
}

// Export Text Handler
function initExportText() {
    const btn = document.getElementById('exportTextBtn');
    if (btn) {
        btn.addEventListener('click', () => {
            window.location.href = '/api/export/text';
        });
    }
}

// Slide Search Handler
function initSearch() {
    const searchInput = document.getElementById('slideSearchInput');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            const query = e.target.value.toLowerCase().trim();
            const cards = document.querySelectorAll('.slide-card');

            cards.forEach(card => {
                const text = card.textContent.toLowerCase();
                if (!query || text.includes(query)) {
                    card.style.display = 'block';
                } else {
                    card.style.display = 'none';
                }
            });
        });
    }
}

// File Upload Logic
function initFileUpload() {
    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('fileInput');
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
        if (files.length > 0) {
            handleFileUpload(files[0]);
        }
    });

    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleFileUpload(e.target.files[0]);
        }
    });

    reuploadBtn.addEventListener('click', () => {
        document.getElementById('workspaceSection').classList.add('hidden');
        document.getElementById('uploadSection').classList.remove('hidden');
        fileInput.value = '';
    });
}

async function handleFileUpload(file) {
    hideError();
    if (!file.name.toLowerCase().endsWith('.pptx')) {
        showError('Please upload a valid PowerPoint (.pptx) file.');
        return;
    }

    const uploadSection = document.getElementById('uploadSection');
    const loadingOverlay = document.getElementById('loadingOverlay');
    const workspaceSection = document.getElementById('workspaceSection');

    uploadSection.classList.add('hidden');
    loadingOverlay.classList.remove('hidden');

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch('/api/upload', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Upload failed');
        }

        const data = await response.json();
        presentationData = data;

        renderSlides(data.slides);

        document.getElementById('loadedFileName').textContent = data.filename;
        document.getElementById('slideCountBadge').textContent = `${data.total_slides} Slides Extracted`;
        document.getElementById('tabSlideCount').textContent = data.total_slides;

        loadingOverlay.classList.add('hidden');
        workspaceSection.classList.remove('hidden');

    } catch (err) {
        showError('Error parsing PowerPoint file: ' + err.message);
        loadingOverlay.classList.add('hidden');
        uploadSection.classList.remove('hidden');
    }
}

// Render Slides & Speaker Notes
function renderSlides(slides) {
    const container = document.getElementById('slidesContainer');
    container.innerHTML = '';

    slides.forEach(slide => {
        const card = document.createElement('div');
        card.className = 'slide-card';

        const header = document.createElement('div');
        header.className = 'slide-card-header';
        header.innerHTML = `
            <div>
                <span class="slide-title">${escapeHtml(slide.title)}</span>
                <span class="slide-num-badge" style="margin-left: 8px;">Slide ${slide.slide_number}</span>
            </div>
            <button class="teach-slide-btn" onclick="teachSlide(${slide.slide_number}, '${escapeHtml(slide.title).replace(/'/g, "\\'")}')">
                <i class="fa-solid fa-graduation-cap"></i> Teach Me This Slide
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
                <i class="fa-solid fa-note-sticky"></i> Speaker Notes / Under-slide Info:
            </div>
            <div class="speaker-notes-content">${hasNotes ? escapeHtml(slide.speaker_notes) : '<em>No speaker notes present on this slide.</em>'}</div>
        `;
        body.appendChild(notesBox);

        card.appendChild(header);
        card.appendChild(body);
        container.appendChild(card);
    });
}

function teachSlide(num, title) {
    // Switch to Chat tab
    const chatTabBtn = document.querySelector('.tab-btn[data-tab="chatTab"]');
    if (chatTabBtn) chatTabBtn.click();

    sendSuggestedQuestion(`Teach me Slide ${num}: "${title}". Explain all points and hidden speaker notes in simple terms.`);
}

// Navigation Tabs
function initTabs() {
    const tabBtns = document.querySelectorAll('.tab-btn');
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetTab = btn.getAttribute('data-tab');

            tabBtns.forEach(b => {
                b.classList.remove('active');
                b.setAttribute('aria-selected', 'false');
            });
            document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));

            btn.classList.add('active');
            btn.setAttribute('aria-selected', 'true');
            document.getElementById(targetTab).classList.add('active');
        });
    });

    document.getElementById('generateSummaryBtn').addEventListener('click', loadStudySummary);
    document.getElementById('generateFlashcardsBtn').addEventListener('click', loadFlashcards);
    document.getElementById('generateQuizBtn').addEventListener('click', loadQuiz);
}

// 1. Study Guide Summary
async function loadStudySummary() {
    hideError();
    const container = document.getElementById('summaryContainer');
    container.innerHTML = `<div class="loading-overlay"><div class="spinner"></div><p>Generating comprehensive study guide...</p></div>`;

    try {
        const res = await fetch('/api/study/summary', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_key: getApiKey() })
        });
        
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Failed to generate study guide');
        }

        const data = await res.json();

        let html = `
            <div class="summary-section">
                <h3><i class="fa-solid fa-heading"></i> Overview</h3>
                <p style="font-size: 15px; line-height: 1.6;">${escapeHtml(data.summary)}</p>
            </div>

            <div class="summary-section">
                <h3><i class="fa-solid fa-lightbulb"></i> Key Concepts Breakdown</h3>
                <div class="concept-grid">
        `;

        (data.key_concepts || []).forEach(c => {
            html += `
                <div class="concept-card">
                    <h4>${escapeHtml(c.concept)}</h4>
                    <p>${escapeHtml(c.explanation)}</p>
                    <span style="font-size: 11px; color: var(--primary); font-weight: 700; display: block; margin-top: 8px;">
                        📌 Ref: ${escapeHtml(c.slides_referenced || '')}
                    </span>
                </div>
            `;
        });

        html += `</div></div>`;

        if (data.speaker_note_highlights && data.speaker_note_highlights.length > 0) {
            html += `
                <div class="summary-section">
                    <h3><i class="fa-solid fa-sticky-note"></i> Key Speaker Notes Highlights</h3>
                    <ul style="padding-left: 20px; line-height: 1.6;">
            `;
            data.speaker_note_highlights.forEach(h => {
                html += `<li style="margin-bottom: 6px;">${escapeHtml(h)}</li>`;
            });
            html += `</ul></div>`;
        }

        if (data.study_tips && data.study_tips.length > 0) {
            html += `
                <div class="summary-section">
                    <h3><i class="fa-solid fa-bullseye"></i> Recommended Study Strategy</h3>
                    <ul style="padding-left: 20px; line-height: 1.6;">
            `;
            data.study_tips.forEach(tip => {
                html += `<li style="margin-bottom: 6px;">${escapeHtml(tip)}</li>`;
            });
            html += `</ul></div>`;
        }

        container.innerHTML = html;
    } catch (err) {
        showError('Failed to load study guide: ' + err.message);
        container.innerHTML = `<p class="placeholder-state" style="color: var(--danger);">${escapeHtml(err.message)}</p>`;
    }
}

// 2. Flashcards
async function loadFlashcards() {
    hideError();
    const container = document.getElementById('flashcardsContainer');
    container.innerHTML = `<div class="loading-overlay"><div class="spinner"></div><p>Creating flashcards...</p></div>`;

    try {
        const res = await fetch('/api/study/flashcards', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_key: getApiKey() })
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Failed to generate flashcards');
        }

        const data = await res.json();
        flashcardsList = data.flashcards || [];
        currentFlashcardIndex = 0;

        if (flashcardsList.length === 0) {
            container.innerHTML = `<p class="placeholder-state">No flashcards generated.</p>`;
            return;
        }

        renderCurrentFlashcard();

    } catch (err) {
        showError('Failed to load flashcards: ' + err.message);
        container.innerHTML = `<p class="placeholder-state" style="color: var(--danger);">${escapeHtml(err.message)}</p>`;
    }
}

function renderCurrentFlashcard() {
    const container = document.getElementById('flashcardsContainer');
    const card = flashcardsList[currentFlashcardIndex];

    container.innerHTML = `
        <div class="flashcard-wrapper" onclick="this.querySelector('.flashcard').classList.toggle('flipped')" role="button" tabindex="0" aria-label="Flip flashcard">
            <div class="flashcard">
                <div class="card-face card-front">
                    <span class="card-category">${escapeHtml(card.category || 'Concept')}</span>
                    <div class="card-text">${escapeHtml(card.front)}</div>
                    <span class="card-instruction"><i class="fa-solid fa-hand-pointer"></i> Click card to flip</span>
                </div>
                <div class="card-face card-back">
                    <span class="card-category">Answer / Explanation</span>
                    <div class="card-text">${escapeHtml(card.back)}</div>
                    <span class="card-instruction"><i class="fa-solid fa-rotate"></i> Click to flip back</span>
                </div>
            </div>
        </div>
        <div class="flashcard-controls">
            <button class="btn btn-outline" onclick="prevFlashcard()" ${currentFlashcardIndex === 0 ? 'disabled' : ''} aria-label="Previous card">
                <i class="fa-solid fa-arrow-left"></i> Previous
            </button>
            <span class="deck-progress">Card ${currentFlashcardIndex + 1} of ${flashcardsList.length}</span>
            <button class="btn btn-primary" onclick="nextFlashcard()" ${currentFlashcardIndex === flashcardsList.length - 1 ? 'disabled' : ''} aria-label="Next card">
                Next <i class="fa-solid fa-arrow-right"></i>
            </button>
        </div>
    `;
}

function nextFlashcard() {
    if (currentFlashcardIndex < flashcardsList.length - 1) {
        currentFlashcardIndex++;
        renderCurrentFlashcard();
    }
}

function prevFlashcard() {
    if (currentFlashcardIndex > 0) {
        currentFlashcardIndex--;
        renderCurrentFlashcard();
    }
}

// 3. Quiz
async function loadQuiz() {
    hideError();
    const container = document.getElementById('quizContainer');
    container.innerHTML = `<div class="loading-overlay"><div class="spinner"></div><p>Generating practice questions...</p></div>`;

    try {
        const res = await fetch('/api/study/quiz', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_key: getApiKey() })
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Failed to generate quiz');
        }

        const data = await res.json();
        quizList = data.quiz || [];

        if (quizList.length === 0) {
            container.innerHTML = `<p class="placeholder-state">No quiz questions generated.</p>`;
            return;
        }

        renderQuiz(quizList);

    } catch (err) {
        showError('Failed to load quiz: ' + err.message);
        container.innerHTML = `<p class="placeholder-state" style="color: var(--danger);">${escapeHtml(err.message)}</p>`;
    }
}

function renderQuiz(questions) {
    const container = document.getElementById('quizContainer');
    container.innerHTML = '';

    questions.forEach((q, qIdx) => {
        const qCard = document.createElement('div');
        qCard.className = 'quiz-question-card';
        qCard.id = `qCard_${qIdx}`;

        let optionsHtml = '';
        q.options.forEach((opt, optIdx) => {
            optionsHtml += `
                <button class="quiz-option-btn" onclick="checkQuizAnswer(${qIdx}, ${optIdx}, ${q.answer_index})">
                    ${String.fromCharCode(65 + optIdx)}. ${escapeHtml(opt)}
                </button>
            `;
        });

        qCard.innerHTML = `
            <div class="quiz-q-title">Q${qIdx + 1}. ${escapeHtml(q.question)}</div>
            <div class="quiz-options">${optionsHtml}</div>
            <div id="qExplanation_${qIdx}" class="quiz-explanation hidden">
                <strong>Explanation:</strong> ${escapeHtml(q.explanation || '')}
            </div>
        `;

        container.appendChild(qCard);
    });
}

function checkQuizAnswer(qIdx, selectedIdx, correctIdx) {
    const card = document.getElementById(`qCard_${qIdx}`);
    const buttons = card.querySelectorAll('.quiz-option-btn');
    const explanation = document.getElementById(`qExplanation_${qIdx}`);

    buttons.forEach((btn, idx) => {
        btn.disabled = true;
        if (idx === correctIdx) {
            btn.classList.add('correct');
        } else if (idx === selectedIdx) {
            btn.classList.add('incorrect');
        }
    });

    explanation.classList.remove('hidden');
}

// 4. AI Chat Tutor
function initChat() {
    const sendBtn = document.getElementById('sendChatBtn');
    const input = document.getElementById('chatInput');

    sendBtn.addEventListener('click', handleSendChat);
    input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') handleSendChat();
    });
}

function sendSuggestedQuestion(qText) {
    const input = document.getElementById('chatInput');
    input.value = qText;
    handleSendChat();
}

async function handleSendChat() {
    hideError();
    const input = document.getElementById('chatInput');
    const text = input.value.trim();
    if (!text) return;

    const teacherModeSelect = document.getElementById('teacherModeSelect');
    const selectedMode = teacherModeSelect ? teacherModeSelect.value : 'tutor';

    input.value = '';

    appendChatMessage('user', text);
    chatHistory.push({ role: 'user', content: text });

    const typingId = appendChatMessage('ai', 'ChatGPT AI Teacher is thinking...', true);

    try {
        const res = await fetch('/api/study/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: text,
                teacher_mode: selectedMode,
                chat_history: chatHistory,
                api_key: getApiKey()
            })
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Chat request failed');
        }

        const data = await res.json();
        removeChatMessage(typingId);

        const reply = data.reply || 'Sorry, I could not generate a response.';
        appendChatMessage('ai', reply);
        chatHistory.push({ role: 'assistant', content: reply });

    } catch (err) {
        removeChatMessage(typingId);
        showError('Chat error: ' + err.message);
        appendChatMessage('ai', 'Error: ' + err.message);
    }
}

function appendChatMessage(sender, text, isTyping = false) {
    const container = document.getElementById('chatMessages');
    const msgDiv = document.createElement('div');
    const msgId = 'msg_' + Date.now();
    msgDiv.id = msgId;
    msgDiv.className = `message message-${sender}`;

    msgDiv.innerHTML = `<div class="message-content">${escapeHtml(text)}</div>`;
    container.appendChild(msgDiv);
    container.scrollTop = container.scrollHeight;
    return msgId;
}

function removeChatMessage(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
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
