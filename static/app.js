/* YaSync Frontend Controller */

const sel = document.querySelector.bind(document);


const backToInputBtn = document.getElementById('back-to-input-btn');

// DOM Elements - Input Step
const usernameInput = document.getElementById('yandex-username');
const loadPlaylistsBtn = document.getElementById('load-playlists-btn');
const userInputGroup = document.getElementById('user-input-group');
const playlistSelectGroup = document.getElementById('playlist-select-group');
const playlistsContainer = document.getElementById('playlists-container');
const urlError = document.getElementById('url-error');

// DOM Elements - Steps
const stepInput = document.getElementById('step-input');
const stepProgress = document.getElementById('step-progress');
const stepResult = document.getElementById('step-result');
const restartBtn = document.getElementById('restart-btn');

// Progress elements
const progressTitle = document.getElementById('progress-title');
const progressMessage = document.getElementById('progress-message');
const progressFill = document.getElementById('progress-fill');
const progressCount = document.getElementById('progress-count');
const progressPercent = document.getElementById('progress-percent');
const foundCount = document.getElementById('found-count');
const notfoundCount = document.getElementById('notfound-count');
const foundCounter = document.getElementById('found-counter');

// Result elements
const resultSuccess = document.getElementById('result-success');
const resultError = document.getElementById('result-error');
const resultSummary = document.getElementById('result-summary');
const spotifyLink = document.getElementById('spotify-link');
const errorMessage = document.getElementById('error-message');
const notFoundSection = document.getElementById('not-found-section');
const notFoundList = document.getElementById('not-found-list');
const toggleNotfound = document.getElementById('toggle-notfound');

/* -------------------------------------------------------------------------- */
/* Step Navigation                                                            */
/* -------------------------------------------------------------------------- */

function showStep(step) {
    [stepInput, stepProgress, stepResult].forEach(s => s.classList.remove('active'));
    step.classList.add('active');
}

/* -------------------------------------------------------------------------- */
/* Load Playlists Logic                                                       */
/* -------------------------------------------------------------------------- */

usernameInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && usernameInput.value.trim().length > 0) {
        loadPlaylistsBtn.click();
    }
});

loadPlaylistsBtn.addEventListener('click', async () => {
    const username = usernameInput.value.trim();
    if (!username) {
        urlError.textContent = "Введите логин";
        urlError.classList.remove('hidden');
        return;
    }
    
    urlError.classList.add('hidden');
    loadPlaylistsBtn.style.opacity = '0.5';
    loadPlaylistsBtn.style.pointerEvents = 'none';

    try {
        const res = await fetch(`/api/playlists?username=${encodeURIComponent(username)}`);
        const data = await res.json();

        if (!res.ok) {
            urlError.textContent = data.error || "Ошибка загрузки плейлистов";
            urlError.classList.remove('hidden');
            return;
        }

        userInputGroup.classList.add('hidden');
        playlistSelectGroup.classList.remove('hidden');
        
        playlistsContainer.innerHTML = data.playlists.map(p => `
            <button class="playlist-item-btn" data-owner="${p.owner}" data-kind="${p.kind}">
                <span class="pl-title">${p.title}</span>
                <span class="pl-count">${p.trackCount} треков</span>
            </button>
        `).join('');

        document.querySelectorAll('.playlist-item-btn').forEach(btn => {
            btn.addEventListener('click', () => startImport(btn.dataset.owner, btn.dataset.kind, btn));
        });



    } catch (err) {
        urlError.textContent = "Ошибка сети при загрузке плейлистов";
        urlError.classList.remove('hidden');
    } finally {
        loadPlaylistsBtn.style.opacity = '1';
        loadPlaylistsBtn.style.pointerEvents = 'auto';
    }
});

backToInputBtn.addEventListener('click', () => {
    userInputGroup.classList.remove('hidden');
    playlistSelectGroup.classList.add('hidden');
    playlistsContainer.innerHTML = '';
    usernameInput.focus();
});


/* -------------------------------------------------------------------------- */
/* Start Import                                                               */
/* -------------------------------------------------------------------------- */


/* --- Start Import --- */
async function startImport(owner, kind, btnElement) {
    if (btnElement) {
        btnElement.style.pointerEvents = 'none';
        btnElement.style.opacity = '0.5';
    }
    resetProgress();
    showStep(stepProgress);
    
    progressTitle.textContent = "Подключение...";
    progressMessage.textContent = "Связь с сервером...";
    progressFill.style.width = "2%";
    progressFill.style.background = "#FFDB4D";

    try {
        const res = await fetch('/api/import', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ owner, kind })
        });
        const data = await res.json();

        if (!res.ok) {
            showError(data.error || "Неизвестная ошибка сервера");
            return;
        }

        localStorage.setItem('active_job_id', data.job_id);
        
        listenSSE(data.job_id);

    } catch (err) {
        showError(err.message || "Ошибка соединения");
    }
}



/* -------------------------------------------------------------------------- */
/* SSE Listener                                                               */
/* -------------------------------------------------------------------------- */
function listenSSE(jobId) {
    let source = new EventSource(`/api/stream/${jobId}`);
    let isFinished = false;

    source.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.status === "ping") return;

        updateUIFromData(data);

        if (data.status === "done" || data.status === "error") {
            isFinished = true;
            source.close();
        }
    };

    source.onerror = () => {
        source.close();
        if (isFinished) return;

        console.log("SSE отключился, переходим на ручной опрос сервера...");
        
        const intervalId = setInterval(async () => {
            if (isFinished) {
                clearInterval(intervalId);
                return;
            }
            try {
                const res = await fetch(`/api/job/${jobId}`);
                if (!res.ok) return;
                
                const data = await res.json();
                updateUIFromData(data);

                if (data.status === "done" || data.status === "error") {
                    isFinished = true;
                    clearInterval(intervalId);
                }
            } catch (e) {
                console.log("Ожидание связи...");
            }
        }, 1000); 
    };
}

function updateUIFromData(data) {
    if (data.message && document.getElementById('progress-message')) {
        document.getElementById('progress-message').textContent = data.message;
    }

    if (data.status === "queued") {
        progressTitle.textContent = "Очередь...";
        progressFill.style.width = "2%";
        progressFill.style.background = "#FFDB4D";
    }
    else if (data.status === "fetching") {
        progressFill.style.background = ""; 
        progressTitle.textContent = "Загрузка из Яндекса...";
        progressFill.style.width = "5%";
    }
    else if (data.status === "fetching_done") {
        progressTitle.textContent = data.playlist_title || "Анализ...";
        progressFill.style.width = "10%";
        progressCount.textContent = `0 / ${data.total}`;
    }
    else if (data.status === "searching") {
        progressTitle.textContent = "Поиск в Spotify...";
        if (data.total > 0) {
            const pct = Math.round((data.progress / data.total) * 90) + 10;
            progressFill.style.width = `${pct}%`;
            progressCount.textContent = `${data.progress} / ${data.total}`;
            progressPercent.textContent = Math.round((data.progress / data.total) * 100);
        }
        foundCount.textContent = data.found || 0;
        notfoundCount.textContent = (data.progress - data.found) || 0;
        foundCounter.style.display = "flex";
    }
    else if (data.status === "creating") {
        progressTitle.textContent = "Сохранение...";
        progressFill.style.width = "98%";
    }
    else if (data.status === "done") {
        showResult(data);
    }
    else if (data.status === "error") {
        showError(data.error);
    }
}


/* -------------------------------------------------------------------------- */
/* Show Result                                                                */
/* -------------------------------------------------------------------------- */

function showResult(data) {
    showStep(stepResult);
    resultSuccess.classList.remove('hidden');
    resultError.classList.add('hidden');
	
	localStorage.removeItem('active_job_id');
	saveToHistory(data);
	
    const title = data.playlist_title;
    const found = data.found || 0;
    const total = data.total || 0;
    const elapsed = data.elapsed || 0;
    const pct = total > 0 ? Math.round((found / total) * 100) : 0;

    resultSummary.textContent = `${title} • ${found} из ${total} (${pct}%) • ${elapsed} сек`;
    spotifyLink.href = data.spotify_url;

    const nf = data.not_found || [];
    if (nf.length > 0) {
        notFoundSection.classList.remove('hidden');
        notFoundList.innerHTML = '';
        nf.forEach(track => {
            const li = document.createElement('li');
            li.textContent = track;
            notFoundList.appendChild(li);
        });
    } else {
        notFoundSection.classList.add('hidden');
    }
}

function showError(msg) {
    showStep(stepResult);
    resultSuccess.classList.add('hidden');
    resultError.classList.remove('hidden');
    errorMessage.textContent = msg;
	
	localStorage.removeItem('active_job_id');
}

/* -------------------------------------------------------------------------- */
/* Reset & Restart                                                            */
/* -------------------------------------------------------------------------- */

function resetProgress() {
    progressTitle.textContent = "Подготовка...";
    progressMessage.textContent = "Инициализация...";
    progressFill.style.width = "0%";
    progressCount.textContent = "0 / 0";
    progressPercent.textContent = "0";
    foundCount.textContent = "0";
    notfoundCount.textContent = "0";
    foundCounter.style.display = "none";
}

restartBtn.addEventListener('click', () => {
    userInputGroup.classList.remove('hidden');
    playlistSelectGroup.classList.add('hidden');
    playlistsContainer.innerHTML = '';
    
    showStep(stepInput);
    usernameInput.focus();
});

toggleNotfound.addEventListener('click', () => {
    notFoundList.classList.toggle('hidden');
    toggleNotfound.classList.toggle('open');
});

/* -------------------------------------------------------------------------- */
/* Modals Logic                                                               */
/* -------------------------------------------------------------------------- */

document.querySelectorAll('.nav-btn[data-modal]').forEach(btn => {
    btn.addEventListener('click', () => {
        const modalId = btn.getAttribute('data-modal');
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.add('active');
            document.body.style.overflow = 'hidden';
        }
    });
});

document.querySelectorAll('.modal-close[data-close], .modal-overlay').forEach(el => {
    el.addEventListener('click', (e) => {
        if (e.target === el || el.classList.contains('modal-close')) {
            const overlay = el.closest('.modal-overlay') || el;
            overlay.classList.remove('active');
            document.body.style.overflow = '';
        }
    });
});

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal-overlay.active').forEach(overlay => {
            overlay.classList.remove('active');
            document.body.style.overflow = '';
        });
    }
});

async function loadGlobalStats() {
    try {
        const res = await fetch('/api/stats');
        const data = await res.json();
        const countElement = document.getElementById('global-tracks');
        
        let startObj = { val: 0 };
        let endVal = data.total_tracks_synced;
        
        const duration = 1500;
        const startTime = performance.now();
        
        function updateCounter(currentTime) {
            const elapsed = currentTime - startTime;
            const progress = Math.min(elapsed / duration, 1);
            const easeOut = 1 - Math.pow(1 - progress, 3);
            
            const currentVal = Math.floor(easeOut * endVal);
            countElement.textContent = currentVal.toLocaleString('ru-RU');
            
            if (progress < 1) {
                requestAnimationFrame(updateCounter);
            }
        }
        requestAnimationFrame(updateCounter);
        
    } catch (e) {
        console.log("Stats load error");
    }
}

/* --- Восстановление после обновления страницы --- */
async function checkActiveJob() {
    const activeJobId = localStorage.getItem('active_job_id');
    if (!activeJobId) return; // Нет активных задач

    try {
        const res = await fetch(`/api/job/${activeJobId}`);
        if (!res.ok) {
            localStorage.removeItem('active_job_id');
            return;
        }

        const data = await res.json();

        if (data.status === "done") {
            localStorage.removeItem('active_job_id');
            showResult(data);
        } 
        else if (data.status === "error") {
            localStorage.removeItem('active_job_id');
            showError(data.error);
        } 
        else {
            userInputGroup.classList.add('hidden');
            playlistSelectGroup.classList.add('hidden');
            showStep(stepProgress);
            
            updateUIFromData(data);
            
            listenSSE(activeJobId);
        }
    } catch (e) {
        console.log("Не удалось восстановить сессию", e);
    }
}

checkActiveJob();


/* --- Управление Историей --- */
const HISTORY_KEY = 'yasync_history';

function saveToHistory(jobData) {
    let history = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
    
    const record = {
        username: jobData.owner || 'Неизвестно',
        title: jobData.playlist_title,
        tracks: jobData.total,
        found: jobData.found,
        spotifyUrl: jobData.spotify_url,
        date: new Date().toLocaleString('ru-RU', { 
            day: '2-digit', month: '2-digit', year: '2-digit', 
            hour: '2-digit', minute: '2-digit' 
        })
    };

    history.unshift(record);
    if (history.length > 50) history.pop();

    localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
    renderHistory();
}

function renderHistory() {
    const history = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
    const container = document.getElementById('history-container');
    const clearBtn = document.getElementById('clear-history-btn');

    if (history.length === 0) {
        container.innerHTML = '<p style="text-align: center; color: var(--text-muted); padding: 20px;">История пуста. Перенесите свой первый плейлист!</p>';
        clearBtn.style.display = 'none';
        return;
    }

    let html = `
        <table class="history-table">
            <thead>
                <tr>
                    <th>Логин</th>
                    <th>Плейлист</th>
                    <th>Треков</th>
                    <th>Ссылка</th>
                    <th>Дата</th>
                </tr>
            </thead>
            <tbody>
    `;

    history.forEach(item => {
        html += `
            <tr>
                <td>${item.username}</td>
                <td>${item.title}</td>
                <td>${item.found}/${item.tracks}</td>
                <td><a href="${item.spotifyUrl}" target="_blank" class="history-spotify-link">Слушать</a></td>
                <td class="history-date">${item.date}</td>
            </tr>
        `;
    });

    html += `</tbody></table>`;
    container.innerHTML = html;
    clearBtn.style.display = 'block';
}

document.getElementById('clear-history-btn').addEventListener('click', () => {
    if (confirm('Вы уверены, что хотите очистить историю?')) {
        localStorage.removeItem(HISTORY_KEY);
        renderHistory();
    }
});

renderHistory();
loadGlobalStats();

// Init
usernameInput.focus();
