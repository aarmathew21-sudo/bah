// State
let presentationData = null;
let currentFlashcardIndex = 0;
let flashcardsList = [];
let quizList = [];
let chatHistory = [];

document.addEventListener('DOMContentLoaded', () => {
    initApiKey();
    initFileUpload();
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

// Session restoration on page load/refresh
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
        }
    } catch (err) {
        console.log('Session check:', err.message);
    }
}

// API Key Logic with live verification
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
            updateBadge(false);
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
            if (data.client_available) {
                updateBadge(true);
                if (notify) alert('✅ Gemini API Key connected and verified! AI study features are now active.');
            } else {
                updateBadge(false);
                if (notify) alert('⚠️ Notice: Gemini client could not be initialized with this key. Running in smart local mode.');
            }
        } catch (e) {
            updateBadge(true);
            if (notify) alert('Gemini API Key saved for this session!');
        }
    }

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

// Dynamic Contextual Suggestions Generator based on Document
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
    chips.push({
        text: 'Summarize the big picture and key takeaways across the entire presentation.',
        label: '💡 Master Takeaways & Overview'
    });

    const candidateSlides = slides.filter(s => s.title && s.title.trim().length > 3 && !s.title.toLowerCase().startsWith('slide '));
    const samplePool = candidateSlides.length > 0 ? candidateSlides : slides;

    // Pick up to 2 distinct topics/slides
    const picked = samplePool.slice(0, 3);
    picked.forEach(s => {
        const sNum = s.slide_number || 1;
        const cleanTitle = s.title.replace(/["']/g, '');
        chips.push({
            text: `Teach me Slide ${sNum}: ${cleanTitle} step-by-step with an everyday analogy.`,
            label: `📖 Slide ${sNum}: ${cleanTitle.length > 25 ? cleanTitle.slice(0, 22) + '...' : cleanTitle}`
        });
    });

    const notesSlide = slides.find(s => s.speaker_notes && s.speaker_notes.trim().length > 10);
    if (notesSlide) {
        chips.push({
            text: 'What hidden insights, exam warnings, or test hints are in the presenter notes?',
            label: '📌 Presenter Notes & Test Hints'
        });
    } else {
        chips.push({
            text: 'Explain the most complex mechanism in these slides with a simple mental model.',
            label: '🌟 Intuitive Everyday Analogy'
        });
    }

    chips.push({
        text: 'Quiz me on the main concepts from these documents to test my recall.',
        label: '🎯 Socratic Recall Challenge'
    });

    chipsContainer.innerHTML = chips.map(c => `
        <button class="claude-chip" onclick="sendSuggestedQuestion('${escapeHtml(c.text).replace(/'/g, "\\'")}')">
            <span>${escapeHtml(c.label)}</span>
        </button>
    `).join('');
}

// Export Handlers (.txt and .json)
function initExportText() {
    const txtBtn = document.getElementById('exportTextBtn');
    if (txtBtn) {
        txtBtn.addEventListener('click', () => {
            window.location.href = '/api/export/text';
        });
    }

    const jsonBtn = document.getElementById('exportJsonBtn');
    if (jsonBtn) {
        jsonBtn.addEventListener('click', () => {
            window.location.href = '/api/export/json';
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

let currentDocFilter = 'ALL';

// File Upload Logic (.pptx, .ppt, and .pdf)
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
    const loadingText = document.getElementById('loadingText');

    if (loadingText) {
        loadingText.textContent = fileList.length > 1
            ? `Extracting slides & speaker notes across ${fileList.length} documents...`
            : `Extracting text, slides, and notes...`;
    }

    uploadSection.classList.add('hidden');
    loadingOverlay.classList.remove('hidden');

    const formData = new FormData();
    fileList.forEach(file => {
        formData.append('files', file);
    });

    try {
        const response = await fetch(`/api/upload?mode=${mode}`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Upload failed');
        }

        const data = await response.json();
        presentationData = data;
        currentDocFilter = 'ALL';

        if (mode === 'replace') {
            // Reset downstream study tabs so stale data from old presentations isn't displayed
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
                        <p>Ready to practice active recall? Generate flashcards with SM-2 review scheduling.</p>
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

            // Reset chat history and memory
            chatHistory = [];
        }

        updateWorkspaceHeader(data);
        renderDocFilterBar(data.documents, data.filenames);
        renderSlides(data.slides);
        updateChatSuggestions(data.slides);

        loadingOverlay.classList.add('hidden');
        workspaceSection.classList.remove('hidden');

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
        filenames.forEach((fn, idx) => {
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
        chatStatus.textContent = `Ready • ${totalDocs} document(s) & ${totalSlides} slides in memory`;
    }
}

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

// Render Slides & Speaker/PDF Notes
function renderSlides(slides) {
    const container = document.getElementById('slidesContainer');
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

function teachSlide(num, title) {
    const chatTabBtn = document.querySelector('.tab-btn[data-tab="chatTab"]');
    if (chatTabBtn) chatTabBtn.click();

    sendSuggestedQuestion(`Teach me Page/Slide ${num}: "${title}". Explain all points and speaker/PDF notes in simple terms.`);
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

    document.getElementById('generateSummaryBtn').addEventListener('click', () => loadStudySummary(true));
    document.getElementById('generateFlashcardsBtn').addEventListener('click', regenerateFlashcards);
    document.getElementById('generateQuizBtn').addEventListener('click', () => loadQuiz(true));
}

// 1. Study Guide Summary (Claude Pedagogical Style)
async function loadStudySummary(forceRefresh = false) {
    hideError();
    const container = document.getElementById('summaryContainer');
    container.innerHTML = `<div class="loading-overlay"><div class="spinner"></div><p>Synthesizing intuitive Claude-style study guide with analogies & exam traps...</p></div>`;

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

        // 1. Hero Big Picture & Motivation
        html += `
            <div class="summary-hero-card">
                <div class="summary-hero-badge"><i class="fa-solid fa-graduation-cap"></i> Master Study Blueprint</div>
                <h2>${escapeHtml(data.title || 'Presentation Master Study Guide')}</h2>
                ${data.big_picture ? `<div class="summary-big-picture"><strong>🎯 The Big Picture:</strong> ${escapeHtml(data.big_picture)}</div>` : ''}
                <p class="summary-overview-text">${escapeHtml(data.summary || '')}</p>
            </div>
        `;

        // 2. Simple Analogies & Mental Models (Claude-style)
        if (data.analogies && data.analogies.length > 0) {
            html += `
                <div class="summary-section">
                    <div class="section-title-row">
                        <span class="section-icon-badge badge-analogy"><i class="fa-solid fa-lightbulb"></i></span>
                        <div>
                            <h3>Simple Analogies & Mental Models</h3>
                            <p class="section-subtitle">Real-world comparisons that make abstract mechanisms click instantly.</p>
                        </div>
                    </div>
                    <div class="analogies-grid">
            `;
            data.analogies.forEach(a => {
                html += `
                    <div class="analogy-card">
                        <div class="analogy-topic"><i class="fa-solid fa-bolt"></i> ${escapeHtml(a.topic || 'Core Concept')}</div>
                        <div class="analogy-quote">
                            <span class="analogy-lead">💡 Analogy:</span> ${escapeHtml(a.analogy || '')}
                        </div>
                        ${a.why_it_works ? `<div class="analogy-why"><strong>Why it works:</strong> ${escapeHtml(a.why_it_works)}</div>` : ''}
                    </div>
                `;
            });
            html += `</div></div>`;
        }

        // 3. Core Concepts Breakdown
        if (data.key_concepts && data.key_concepts.length > 0) {
            html += `
                <div class="summary-section">
                    <div class="section-title-row">
                        <span class="section-icon-badge badge-concepts"><i class="fa-solid fa-cubes"></i></span>
                        <div>
                            <h3>Core Concepts & Step-by-Step Logic</h3>
                            <p class="section-subtitle">Plain-English explanations and step-by-step mechanisms.</p>
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
                            <ol>
                                ${c.how_it_works_steps.map(s => `<li>${escapeHtml(s)}</li>`).join('')}
                            </ol>
                        </div>
                    `;
                }

                html += `
                    <div class="concept-card">
                        <div class="concept-card-header">
                            <h4>${escapeHtml(c.concept)}</h4>
                            ${c.slides_referenced ? `<span class="concept-slide-tag">📌 ${escapeHtml(c.slides_referenced)}</span>` : ''}
                        </div>
                        <p class="concept-explanation">${escapeHtml(c.explanation)}</p>
                        ${c.real_world_analogy ? `<div class="concept-analogy-box"><i class="fa-solid fa-wand-magic-sparkles"></i> <em>${escapeHtml(c.real_world_analogy)}</em></div>` : ''}
                        ${stepsHtml}
                    </div>
                `;
            });
            html += `</div></div>`;
        }

        // 4. Exam Traps & Common Confusions
        if (data.exam_traps && data.exam_traps.length > 0) {
            html += `
                <div class="summary-section">
                    <div class="section-title-row">
                        <span class="section-icon-badge badge-traps"><i class="fa-solid fa-triangle-exclamation"></i></span>
                        <div>
                            <h3>⚠️ Exam Traps & Common Mistakes to Avoid</h3>
                            <p class="section-subtitle">Classic pitfalls and how to guarantee full marks on your test.</p>
                        </div>
                    </div>
                    <div class="traps-grid">
            `;
            data.exam_traps.forEach(t => {
                html += `
                    <div class="trap-card">
                        <div class="trap-warning">
                            <i class="fa-solid fa-circle-xmark"></i> <strong>Trap:</strong> ${escapeHtml(t.trap || '')}
                        </div>
                        <div class="trap-fix">
                            <i class="fa-solid fa-circle-check"></i> <strong>The Fix:</strong> ${escapeHtml(t.fix || '')}
                        </div>
                    </div>
                `;
            });
            html += `</div></div>`;
        }

        // 5. Memory Hooks & Mnemonics
        if (data.memory_hooks && data.memory_hooks.length > 0) {
            html += `
                <div class="summary-section">
                    <div class="section-title-row">
                        <span class="section-icon-badge badge-memory"><i class="fa-solid fa-brain"></i></span>
                        <div>
                            <h3>🧠 Memory Hooks & Mnemonics</h3>
                            <p class="section-subtitle">Quick mental shortcuts for recall during high-pressure exams.</p>
                        </div>
                    </div>
                    <div class="memory-hooks-container">
            `;
            data.memory_hooks.forEach(hook => {
                html += `
                    <div class="memory-hook-card">
                        <i class="fa-solid fa-key"></i> <span>${escapeHtml(hook)}</span>
                    </div>
                `;
            });
            html += `</div></div>`;
        }

        // 6. Speaker Notes & Instructor Highlights
        if (data.speaker_note_highlights && data.speaker_note_highlights.length > 0) {
            html += `
                <div class="summary-section">
                    <div class="section-title-row">
                        <span class="section-icon-badge badge-notes"><i class="fa-solid fa-note-sticky"></i></span>
                        <div>
                            <h3>📌 Presenter Notes & Instructor Clues</h3>
                            <p class="section-subtitle">Insights and test hints extracted directly from speaker annotations.</p>
                        </div>
                    </div>
                    <ul class="summary-bullet-list">
            `;
            data.speaker_note_highlights.forEach(h => {
                html += `<li><i class="fa-solid fa-angle-right"></i> ${escapeHtml(h)}</li>`;
            });
            html += `</ul></div>`;
        }

        // 7. Study Tips & Strategy
        if (data.study_tips && data.study_tips.length > 0) {
            html += `
                <div class="summary-section">
                    <div class="section-title-row">
                        <span class="section-icon-badge badge-strategy"><i class="fa-solid fa-bullseye"></i></span>
                        <div>
                            <h3>🚀 Master Study Strategy</h3>
                            <p class="section-subtitle">Recommended active-recall workflow for maximum retention.</p>
                        </div>
                    </div>
                    <ul class="summary-bullet-list">
            `;
            data.study_tips.forEach(tip => {
                html += `<li><i class="fa-solid fa-check"></i> ${escapeHtml(tip)}</li>`;
            });
            html += `</ul></div>`;
        }

        container.innerHTML = html;
    } catch (err) {
        showError('Failed to load study guide: ' + err.message);
        container.innerHTML = `<p class="placeholder-state" style="color: var(--danger);">${escapeHtml(err.message)}</p>`;
    }
}

// 2. Flashcards (SM-2 Spaced Repetition)
async function loadFlashcards() {
    hideError();
    const container = document.getElementById('flashcardsContainer');

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

        const dueBadge = document.getElementById('dueCardsBadge');
        if (dueBadge) {
            dueBadge.textContent = `${data.total_due || 0} Cards Due Today`;
        }

        if (flashcardsList.length === 0) {
            container.innerHTML = `
                <div class="placeholder-state">
                    <i class="fa-solid fa-circle-check placeholder-icon" style="color: var(--success);"></i>
                    <h3>🎉 All Caught Up!</h3>
                    <p>No cards due for review today. Great job! Come back later for your next spaced repetition review.</p>
                </div>
            `;
            return;
        }

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

    container.innerHTML = `
        <div class="flashcard-wrapper" onclick="this.querySelector('.flashcard').classList.toggle('flipped')" role="button" tabindex="0" aria-label="Flip flashcard">
            <div class="flashcard">
                <div class="card-face card-front">
                    <span class="card-category">${escapeHtml(card.category || 'Concept')}</span>
                    <div class="card-text">${escapeHtml(card.front)}</div>
                    <span class="card-instruction"><i class="fa-solid fa-hand-pointer"></i> Click card to flip</span>
                </div>
                <div class="card-face card-back">
                    <span class="card-category">Answer & SM-2 Rating</span>
                    <div class="card-text" style="font-size: 15px;">${escapeHtml(card.back)}</div>
                    
                    <div class="sm2-rating-container" onclick="event.stopPropagation()">
                        <button class="sm2-rating-btn btn-again" onclick="submitCardReview('${card.card_id}', 'again')">
                            <span>🔴 Again</span>
                            <span style="font-size: 10px; opacity: 0.8;">1 day</span>
                        </button>
                        <button class="sm2-rating-btn btn-hard" onclick="submitCardReview('${card.card_id}', 'hard')">
                            <span>🟠 Hard</span>
                            <span style="font-size: 10px; opacity: 0.8;">Harder</span>
                        </button>
                        <button class="sm2-rating-btn btn-good" onclick="submitCardReview('${card.card_id}', 'good')">
                            <span>🟢 Good</span>
                            <span style="font-size: 10px; opacity: 0.8;">Normal</span>
                        </button>
                        <button class="sm2-rating-btn btn-easy" onclick="submitCardReview('${card.card_id}', 'easy')">
                            <span>🔵 Easy</span>
                            <span style="font-size: 10px; opacity: 0.8;">Bonus</span>
                        </button>
                    </div>
                </div>
            </div>
        </div>
        <div class="flashcard-controls">
            <span class="deck-progress">Due Card ${currentFlashcardIndex + 1} of ${flashcardsList.length}</span>
        </div>
    `;
}

async function submitCardReview(cardId, rating) {
    hideError();
    try {
        const res = await fetch('/api/study/flashcards/review', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ card_id: cardId, rating: rating })
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Failed to record card review');
        }

        // Advance to next due card
        await loadFlashcards();

    } catch (err) {
        showError('Review error: ' + err.message);
    }
}

let examPackData = {
    five_mark_questions: [],
    ten_mark_questions: [],
    practice_mcqs: []
};
let currentExamFilter = 'all';

// 3. University Exam Prep (5-Mark, 10-Mark, & Practice MCQs)
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
    container.innerHTML = '';

    const filter = currentExamFilter;
    let renderedCount = 0;

    // 1. Render 5-Mark Conceptual Short-Answer Questions
    if ((filter === 'all' || filter === '5mark') && examPackData.five_mark_questions.length > 0) {
        if (filter === 'all') {
            const sectionHeader = document.createElement('div');
            sectionHeader.className = 'exam-section-divider';
            sectionHeader.innerHTML = `
                <div class="exam-section-title">
                    <span class="exam-type-badge badge-5m"><i class="fa-solid fa-bolt"></i> Section A: 5-Mark Conceptual Questions</span>
                    <span class="exam-section-hint">High-yield short answer questions with marking rubrics, analogies & traps</span>
                </div>
            `;
            container.appendChild(sectionHeader);
        }

        examPackData.five_mark_questions.forEach((q, idx) => {
            renderedCount++;
            const card = document.createElement('div');
            card.className = 'exam-q-card five-mark-card';
            card.id = `fiveMarkCard_${idx}`;

            let rubricListHtml = '';
            (q.marking_rubric || []).forEach(r => {
                rubricListHtml += `<li><i class="fa-solid fa-check-double"></i> ${escapeHtml(r)}</li>`;
            });

            card.innerHTML = `
                <div class="exam-q-header">
                    <div class="exam-q-tags">
                        <span class="exam-points-badge badge-5m">⚡ 5 MARKS</span>
                        <span class="exam-topic-tag">${escapeHtml(q.topic || 'Security Architecture')}</span>
                    </div>
                    <div class="exam-q-number">Q${idx + 1}</div>
                </div>

                <div class="exam-q-text">${escapeHtml(q.question)}</div>

                <!-- Self-Testing Practice Draft Notepad -->
                <div class="exam-practice-box">
                    <div class="exam-practice-header">
                        <span><i class="fa-solid fa-pen-to-square"></i> Active Recall Practice Draft (Type before revealing answer)</span>
                        <span class="practice-char-count" id="charCount_5m_${idx}">0 words</span>
                    </div>
                    <textarea class="exam-draft-textarea" id="draft_5m_${idx}" placeholder="Write your key points, definitions, and mechanisms here to test yourself..." rows="3" oninput="updateWordCount('draft_5m_${idx}', 'charCount_5m_${idx}')"></textarea>
                </div>

                <!-- Action Button Bar -->
                <div class="exam-action-bar">
                    <button class="btn btn-primary btn-sm" onclick="toggleExamSolution('sol_5m_${idx}', this)">
                        <i class="fa-solid fa-eye"></i> Reveal Model Answer & Rubric
                    </button>
                    <button class="btn btn-outline btn-sm" onclick="teachExamQuestion('${escapeHtml(q.question).replace(/'/g, "\\'")}')">
                        <i class="fa-solid fa-robot"></i> Ask AI Teacher
                    </button>
                </div>

                <!-- Expandable Solution & Marking Details -->
                <div id="sol_5m_${idx}" class="exam-solution-collapse hidden">
                    <!-- Marking Scheme Rubric -->
                    <div class="exam-rubric-box">
                        <div class="exam-rubric-title"><i class="fa-solid fa-clipboard-list"></i> Official Marking Scheme Breakdown (5.0 Marks Total)</div>
                        <ul class="exam-rubric-list">${rubricListHtml}</ul>
                    </div>

                    <!-- Model Solution -->
                    <div class="exam-model-answer-box">
                        <div class="exam-model-title"><i class="fa-solid fa-award"></i> Comprehensive Model Solution</div>
                        <div class="exam-model-text">${renderMarkdownSafely(q.model_answer)}</div>
                    </div>

                    <!-- Mental Model Analogy -->
                    ${q.analogy ? `
                    <div class="exam-analogy-box">
                        <div class="exam-analogy-title"><i class="fa-regular fa-lightbulb"></i> Intuitive Mental Model</div>
                        <div class="exam-analogy-text">${renderMarkdownSafely(q.analogy)}</div>
                    </div>` : ''}

                    <!-- Common Exam Trap -->
                    ${q.exam_trap ? `
                    <div class="exam-trap-box">
                        <div class="exam-trap-title"><i class="fa-solid fa-triangle-exclamation"></i> Examiner Warning & Common Exam Trap</div>
                        <div class="exam-trap-text">${renderMarkdownSafely(q.exam_trap)}</div>
                    </div>` : ''}
                </div>
            `;
            container.appendChild(card);
        });
    }

    // 2. Render 10-Mark Comprehensive Case Studies
    if ((filter === 'all' || filter === '10mark') && examPackData.ten_mark_questions.length > 0) {
        if (filter === 'all') {
            const sectionHeader = document.createElement('div');
            sectionHeader.className = 'exam-section-divider';
            sectionHeader.innerHTML = `
                <div class="exam-section-title">
                    <span class="exam-type-badge badge-10m"><i class="fa-solid fa-trophy"></i> Section B: 10-Mark Comprehensive Case Studies</span>
                    <span class="exam-section-hint">Multi-part architectural design, threat modeling scenarios & examiner rubrics</span>
                </div>
            `;
            container.appendChild(sectionHeader);
        }

        examPackData.ten_mark_questions.forEach((q, idx) => {
            renderedCount++;
            const card = document.createElement('div');
            card.className = 'exam-q-card ten-mark-card';
            card.id = `tenMarkCard_${idx}`;

            let partsHtml = '';
            (q.parts || []).forEach(p => {
                partsHtml += `
                    <div class="case-part-box">
                        <div class="case-part-header">
                            <span class="case-part-badge">Part ${escapeHtml(p.part)} (${p.marks} Marks)</span>
                        </div>
                        <div class="case-part-q">${escapeHtml(p.question)}</div>
                        <div class="case-part-model">
                            <div class="case-model-title"><i class="fa-solid fa-check"></i> Model Solution:</div>
                            <div>${renderMarkdownSafely(p.model_answer)}</div>
                        </div>
                    </div>
                `;
            });

            card.innerHTML = `
                <div class="exam-q-header">
                    <div class="exam-q-tags">
                        <span class="exam-points-badge badge-10m">🏆 10 MARKS CASE STUDY</span>
                        <span class="exam-topic-tag">${escapeHtml(q.title || 'Architectural Threat Modeling')}</span>
                    </div>
                    <div class="exam-q-number">Case Study ${idx + 1}</div>
                </div>

                <!-- Scenario Presentation -->
                <div class="case-scenario-box">
                    <div class="case-scenario-label"><i class="fa-solid fa-building-shield"></i> Enterprise Architectural Scenario:</div>
                    <div class="case-scenario-text">${escapeHtml(q.scenario)}</div>
                </div>

                <!-- Self-Testing Practice Draft Notepad -->
                <div class="exam-practice-box">
                    <div class="exam-practice-header">
                        <span><i class="fa-solid fa-pen-to-square"></i> Case Study Architectural Scratchpad</span>
                        <span class="practice-char-count" id="charCount_10m_${idx}">0 words</span>
                    </div>
                    <textarea class="exam-draft-textarea" id="draft_10m_${idx}" placeholder="Draft your multi-part architectural solution (Part A, Part B, Part C) here..." rows="4" oninput="updateWordCount('draft_10m_${idx}', 'charCount_10m_${idx}')"></textarea>
                </div>

                <!-- Action Button Bar -->
                <div class="exam-action-bar">
                    <button class="btn btn-primary btn-sm" onclick="toggleExamSolution('sol_10m_${idx}', this)">
                        <i class="fa-solid fa-eye"></i> Reveal Full 10-Mark Solution & Rubric
                    </button>
                    <button class="btn btn-outline btn-sm" onclick="teachExamQuestion('Case Study: ${escapeHtml(q.title).replace(/'/g, "\\'")}. Scenario: ${escapeHtml(q.scenario).replace(/'/g, "\\'")}')">
                        <i class="fa-solid fa-robot"></i> Ask AI Teacher
                    </button>
                </div>

                <!-- Expandable Solution & Marking Details -->
                <div id="sol_10m_${idx}" class="exam-solution-collapse hidden">
                    <!-- Marking Scheme Rubric -->
                    ${q.marking_rubric ? `
                    <div class="exam-rubric-box">
                        <div class="exam-rubric-title"><i class="fa-solid fa-clipboard-list"></i> Grading Rubric Criteria (10.0 Marks Total)</div>
                        <div class="exam-rubric-text">${renderMarkdownSafely(q.marking_rubric)}</div>
                    </div>` : ''}

                    <!-- Parts Breakdown -->
                    <div class="case-parts-container">
                        ${partsHtml}
                    </div>

                    <!-- Examiner Tips -->
                    ${q.examiner_tips ? `
                    <div class="exam-analogy-box">
                        <div class="exam-analogy-title"><i class="fa-solid fa-graduation-cap"></i> Senior Examiner Distinction Advice</div>
                        <div class="exam-analogy-text">${renderMarkdownSafely(q.examiner_tips)}</div>
                    </div>` : ''}
                </div>
            `;
            container.appendChild(card);
        });
    }

    // 3. Render Practice MCQs
    if ((filter === 'all' || filter === 'mcqs') && examPackData.practice_mcqs.length > 0) {
        if (filter === 'all') {
            const sectionHeader = document.createElement('div');
            sectionHeader.className = 'exam-section-divider';
            sectionHeader.innerHTML = `
                <div class="exam-section-title">
                    <span class="exam-type-badge badge-mcq"><i class="fa-solid fa-list-check"></i> Section C: Interactive Practice MCQs</span>
                    <span class="exam-section-hint">Scenario-based multiple choice with instant grading and explanations</span>
                </div>
            `;
            container.appendChild(sectionHeader);
        }

        examPackData.practice_mcqs.forEach((q, qIdx) => {
            renderedCount++;
            const qCard = document.createElement('div');
            qCard.className = 'quiz-question-card mcq-card';
            qCard.id = `mcqCard_${qIdx}`;

            let optionsHtml = '';
            q.options.forEach((opt, optIdx) => {
                optionsHtml += `
                    <button class="quiz-option-btn" onclick="checkExamMcqAnswer(${qIdx}, ${optIdx}, ${q.answer_index})">
                        ${String.fromCharCode(65 + optIdx)}. ${escapeHtml(opt)}
                    </button>
                `;
            });

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

    if (renderedCount === 0) {
        container.innerHTML = `<p class="placeholder-state">No questions found in this category.</p>`;
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
    const chatTabBtn = document.querySelector('.tab-btn[data-tab="chatTab"]');
    if (chatTabBtn) chatTabBtn.click();
    sendSuggestedQuestion(`Help me master this exam question in depth: "${questionText}". Explain the marking rubric, model answer, and key edge cases in simple terms.`);
}

function checkExamMcqAnswer(qIdx, selectedIdx, correctIdx) {
    const card = document.getElementById(`mcqCard_${qIdx}`);
    if (!card) return;
    const buttons = card.querySelectorAll('.quiz-option-btn');
    const explanation = document.getElementById(`mcqExplanation_${qIdx}`);

    buttons.forEach((btn, idx) => {
        btn.disabled = true;
        if (idx === correctIdx) {
            btn.classList.add('correct');
        } else if (idx === selectedIdx) {
            btn.classList.add('incorrect');
        }
    });

    if (explanation) explanation.classList.remove('hidden');
}

// 4. AI Chat Tutor (Claude-inspired)
function initChat() {
    const sendBtn = document.getElementById('sendChatBtn');
    const input = document.getElementById('chatInput');
    const modeSelect = document.getElementById('teacherModeSelect');
    const modeTag = document.getElementById('currentModeTag');

    if (modeSelect && modeTag) {
        modeSelect.addEventListener('change', () => {
            const modeText = modeSelect.options[modeSelect.selectedIndex].text;
            modeTag.innerHTML = `<i class="fa-solid fa-wand-magic-sparkles"></i> ${escapeHtml(modeText)}`;
        });
    }

    if (input) {
        // Auto-resizing textarea
        input.addEventListener('input', () => {
            input.style.height = 'auto';
            input.style.height = Math.min(input.scrollHeight, 160) + 'px';
        });

        // Keyboard handler: Enter sends, Shift+Enter newlines
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

function sendSuggestedQuestion(qText) {
    const input = document.getElementById('chatInput');
    if (!input) return;
    input.value = qText;
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 160) + 'px';
    handleSendChat();
}

async function clearChatHistory() {
    chatHistory = [];
    try {
        await fetch('/api/study/chat/memory', { method: 'DELETE' });
    } catch (e) {}

    const memBar = document.getElementById('sessionMemoryBar');
    if (memBar) memBar.classList.add('hidden');

    const container = document.getElementById('chatMessages');
    if (container) {
        container.innerHTML = `
            <div class="claude-msg claude-msg-ai">
                <div class="claude-msg-avatar">
                    <i class="fa-solid fa-wand-magic-sparkles"></i>
                </div>
                <div class="claude-msg-body">
                    <div class="claude-msg-meta">
                        <span class="claude-msg-author">Claude / GPT AI Tutor</span>
                        <span class="claude-msg-badge">Active Session</span>
                    </div>
                    <div class="claude-msg-content markdown-body">
                        Conversation and session memory reset. What concept or slide would you like to explore next?
                    </div>
                </div>
            </div>
        `;
    }
}

async function clearSessionMemoryOnly() {
    try {
        await fetch('/api/study/chat/memory', { method: 'DELETE' });
        const memBar = document.getElementById('sessionMemoryBar');
        if (memBar) memBar.classList.add('hidden');
        alert('Active session memory reset.');
    } catch (e) {
        console.error(e);
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

function copyMessageText(btn) {
    const parentMsg = btn.closest('.claude-msg-body');
    if (!parentMsg) return;
    const contentEl = parentMsg.querySelector('.claude-msg-content');
    if (!contentEl) return;

    const text = contentEl.innerText || contentEl.textContent;
    navigator.clipboard.writeText(text).then(() => {
        const origHtml = btn.innerHTML;
        btn.innerHTML = `<i class="fa-solid fa-check" style="color: #16a34a;"></i> Copied!`;
        setTimeout(() => {
            btn.innerHTML = origHtml;
        }, 2000);
    }).catch(err => {
        console.error('Failed to copy text', err);
    });
}

async function handleSendChat() {
    hideError();
    const input = document.getElementById('chatInput');
    if (!input) return;
    const text = input.value.trim();
    if (!text) return;

    const teacherModeSelect = document.getElementById('teacherModeSelect');
    const selectedMode = teacherModeSelect ? teacherModeSelect.value : 'tutor';

    input.value = '';
    input.style.height = 'auto';

    appendChatMessage('user', text);
    chatHistory.push({ role: 'user', content: text });

    const typingId = appendChatMessage('ai', '', true);

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
        appendChatMessage('ai', reply, false, true);
        chatHistory.push({ role: 'assistant', content: reply });

        if (data.session_memory) {
            updateSessionMemoryUI(data.session_memory);
        }

    } catch (err) {
        removeChatMessage(typingId);
        showError('Chat error: ' + err.message);
        appendChatMessage('ai', '⚠️ **Error:** ' + err.message);
    }
}

function renderMarkdownSafely(text) {
    if (window.marked && typeof window.marked.parse === 'function') {
        try {
            return window.marked.parse(text);
        } catch (e) {
            console.warn('Marked parse error, fallback to html-escape', e);
        }
    }
    return escapeHtml(text).replace(/\n/g, '<br/>');
}

function appendChatMessage(sender, text, isTyping = false, addAudio = false) {
    const container = document.getElementById('chatMessages');
    if (!container) return;
    const msgDiv = document.createElement('div');
    const msgId = 'msg_' + Date.now() + '_' + Math.floor(Math.random() * 1000);
    msgDiv.id = msgId;

    const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    if (sender === 'user') {
        msgDiv.className = 'claude-msg claude-msg-user';
        msgDiv.innerHTML = `
            <div class="claude-msg-body">
                ${escapeHtml(text).replace(/\n/g, '<br/>')}
            </div>
        `;
    } else {
        msgDiv.className = 'claude-msg claude-msg-ai';
        if (isTyping) {
            msgDiv.innerHTML = `
                <div class="claude-msg-avatar">
                    <i class="fa-solid fa-wand-magic-sparkles"></i>
                </div>
                <div class="claude-msg-body" style="padding: 12px 18px;">
                    <div class="claude-typing-dots">
                        <span></span><span></span><span></span>
                    </div>
                </div>
            `;
        } else {
            const renderedHtml = renderMarkdownSafely(text);
            const safeTextForAudio = escapeHtml(text).replace(/[`\\]/g, '');

            let actionsHtml = `
                <div class="claude-msg-actions">
                    <button class="claude-action-btn" onclick="speakText(\`${safeTextForAudio}\`)" title="Read out loud">
                        <i class="fa-solid fa-volume-high"></i> Listen
                    </button>
                    <button class="claude-action-btn" onclick="copyMessageText(this)" title="Copy message">
                        <i class="fa-regular fa-copy"></i> Copy
                    </button>
                    <span class="claude-msg-time">${timeStr}</span>
                </div>
            `;

            msgDiv.innerHTML = `
                <div class="claude-msg-avatar">
                    <i class="fa-solid fa-wand-magic-sparkles"></i>
                </div>
                <div class="claude-msg-body">
                    <div class="claude-msg-meta">
                        <span class="claude-msg-author">AI Teacher</span>
                        <span class="claude-msg-badge">Assistant</span>
                    </div>
                    <div class="claude-msg-content markdown-body">
                        ${renderedHtml}
                    </div>
                    ${actionsHtml}
                </div>
            `;
        }
    }

    container.appendChild(msgDiv);
    
    // Highlight syntax if code blocks exist
    if (window.hljs && !isTyping) {
        msgDiv.querySelectorAll('pre code').forEach(block => {
            window.hljs.highlightElement(block);
        });
    }

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

// --- QUIZ MASTER HUB INTERACTIVE EXAM ENGINE ---
let quizMasterState = {
    examTitle: '',
    questions: [],
    currentIndex: 0,
    userAnswers: {}, // question index -> option index
    flagged: {}, // question index -> boolean
    startTime: null,
    timerInterval: null,
    timeLimitSeconds: 300,
    remainingSeconds: 300
};

async function startQuizMasterExam() {
    hideError();
    const diff = document.getElementById('qmDifficulty').value;
    const count = parseInt(document.getElementById('qmCount').value, 10);
    const topic = document.getElementById('qmTopic').value.trim();

    const setupCard = document.getElementById('qmSetupCard');
    const examCard = document.getElementById('qmExamCard');
    const scorecardCard = document.getElementById('qmScorecardCard');
    const historyCard = document.getElementById('qmHistoryCard');

    try {
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
        
        quizMasterState = {
            examTitle: data.exam_title,
            questions: data.questions || [],
            currentIndex: 0,
            userAnswers: {},
            flagged: {},
            startTime: Date.now(),
            timerInterval: null,
            timeLimitSeconds: data.time_limit_seconds || count * 60,
            remainingSeconds: data.time_limit_seconds || count * 60
        };

        if (quizMasterState.questions.length === 0) {
            throw new Error('No exam questions could be generated from document.');
        }

        document.getElementById('qmExamTitle').textContent = data.exam_title;
        setupCard.classList.add('hidden');
        scorecardCard.classList.add('hidden');
        historyCard.classList.add('hidden');
        examCard.classList.remove('hidden');

        startQuizMasterTimer();
        renderQuizMasterNavPills();
        renderQuizMasterCurrentQuestion();

    } catch (err) {
        showError('Quiz Master Error: ' + err.message);
    }
}

function startQuizMasterTimer() {
    if (quizMasterState.timerInterval) {
        clearInterval(quizMasterState.timerInterval);
    }

    const timerDisplay = document.getElementById('qmTimerDisplay');
    const timerWrapper = document.getElementById('qmTimerWrapper');

    updateTimerUI();

    quizMasterState.timerInterval = setInterval(() => {
        quizMasterState.remainingSeconds--;
        updateTimerUI();

        if (quizMasterState.remainingSeconds <= 0) {
            clearInterval(quizMasterState.timerInterval);
            alert('⏱️ Time is up! Submitting your exam now.');
            submitQuizMasterExam();
        }
    }, 1000);

    function updateTimerUI() {
        const mins = Math.floor(Math.max(0, quizMasterState.remainingSeconds) / 60);
        const secs = Math.max(0, quizMasterState.remainingSeconds) % 60;
        const fmt = `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
        timerDisplay.textContent = fmt;

        if (quizMasterState.remainingSeconds <= 60) {
            timerWrapper.classList.add('warning');
        } else {
            timerWrapper.classList.remove('warning');
        }
    }
}

function renderQuizMasterNavPills() {
    const container = document.getElementById('qmNavPills');
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

    document.getElementById('qmQuestionProgress').textContent = `Question ${idx + 1} of ${total}`;

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

    // Footer buttons navigation state
    document.getElementById('qmPrevBtn').disabled = (idx === 0);
    const flagBtn = document.getElementById('qmFlagBtn');
    flagBtn.innerHTML = quizMasterState.flagged[idx] ? `<i class="fa-solid fa-bookmark"></i> Unflag` : `<i class="fa-regular fa-bookmark"></i> Flag Question`;

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
    quizMasterState.userAnswers[idx] = optIdx;
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
        renderQuizMasterNavPills();
        renderQuizMasterCurrentQuestion();
    }
}

function nextQuizMasterQuestion() {
    if (quizMasterState.currentIndex < quizMasterState.questions.length - 1) {
        quizMasterState.currentIndex++;
        renderQuizMasterNavPills();
        renderQuizMasterCurrentQuestion();
    }
}

async function submitQuizMasterExam() {
    if (quizMasterState.timerInterval) {
        clearInterval(quizMasterState.timerInterval);
    }

    const timeSpent = Math.round((Date.now() - quizMasterState.startTime) / 1000);
    let correctCount = 0;
    const details = [];

    quizMasterState.questions.forEach((q, idx) => {
        const userOpt = quizMasterState.userAnswers[idx];
        const isCorrect = (userOpt === q.answer_index);
        if (isCorrect) correctCount++;

        details.push({
            question_id: q.id,
            question: q.question,
            user_option: userOpt !== undefined ? q.options[userOpt] : "No answer selected",
            correct_option: q.options[q.answer_index],
            is_correct: isCorrect,
            explanation: q.explanation
        });
    });

    const total = quizMasterState.questions.length;
    const percent = Math.round((correctCount / total) * 100);

    try {
        const res = await fetch('/api/quizmaster/submit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                exam_title: quizMasterState.examTitle,
                score: correctCount,
                total_questions: total,
                time_spent_seconds: timeSpent,
                details: details
            })
        });

        if (!res.ok) {
            console.error('Quiz Master submit error');
        }
    } catch (e) {
        console.error('Submit API exception:', e.message);
    }

    // Render Scorecard
    document.getElementById('qmExamCard').classList.add('hidden');
    document.getElementById('qmScorecardCard').classList.remove('hidden');

    const gaugePath = document.getElementById('qmGaugePath');
    const percentText = document.getElementById('qmScorePercentText');
    const gradeHeading = document.getElementById('qmScoreGrade');
    const summaryText = document.getElementById('qmScoreSummaryText');

    gaugePath.setAttribute('stroke-dasharray', `${percent}, 100`);
    percentText.textContent = `${percent}%`;

    let grade = 'Mastery Achieved! 🏆';
    if (percent < 50) grade = 'Needs Revision 📚';
    else if (percent < 80) grade = 'Good Progress! 👍';
    gradeHeading.textContent = grade;

    const mins = Math.floor(timeSpent / 60);
    const secs = timeSpent % 60;
    summaryText.textContent = `You scored ${correctCount} out of ${total} questions correctly in ${mins}m ${secs}s.`;

    // Render Review Breakdown
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
                <p style="font-size: 13px; margin-bottom: 4px;"><strong>Your Answer:</strong> <span style="color: ${d.is_correct ? 'var(--success)' : 'var(--danger)'};">${escapeHtml(d.user_option)}</span></p>
                ${!d.is_correct ? `<p style="font-size: 13px; margin-bottom: 4px;"><strong>Correct Answer:</strong> <span style="color: var(--success);">${escapeHtml(d.correct_option)}</span></p>` : ''}
                <div class="quiz-explanation" style="margin-top: 8px;">
                    <strong>Teacher Explanation:</strong> ${escapeHtml(d.explanation)}
                </div>
            </div>
        `;
    });

    reviewContainer.innerHTML = reviewHtml;
}

function resetQuizMasterSetup() {
    if (quizMasterState.timerInterval) {
        clearInterval(quizMasterState.timerInterval);
    }
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
            container.innerHTML = `<p class="placeholder-state">No past exam attempts recorded yet for this document session.</p>`;
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
            const badgeClass = h.percentage >= 80 ? 'badge-active' : (h.percentage >= 50 ? 'badge-fallback' : 'badge-fallback');
            
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

