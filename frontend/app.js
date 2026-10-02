/**
 * Mp3Zip Music Engine - Frontend Reactive Application
 */

let state = {
  jobs: [],
  library: [],
  config: {},
  diagnostics: {},
  ws: null,
  activeTab: 'queue',
  currentAudio: null,
  isPlaying: false
};

// --- Initialization ---
document.addEventListener('DOMContentLoaded', () => {
  initWebSocket();
  setupEventListeners();
  loadInitialData();
});

// --- Tab Navigation ---
function switchTab(tabName) {
  state.activeTab = tabName;
  ['queue', 'library', 'settings'].forEach(t => {
    const el = document.getElementById(`tab-${t}`);
    const btn = document.getElementById(`tab-btn-${t}`);
    if (t === tabName) {
      el.classList.remove('hidden');
      btn.classList.add('active', 'border-brand-500', 'text-brand-400');
      btn.classList.remove('border-transparent', 'text-slate-400');
    } else {
      el.classList.add('hidden');
      btn.classList.remove('active', 'border-brand-500', 'text-brand-400');
      btn.classList.add('border-transparent', 'text-slate-400');
    }
  });

  if (tabName === 'library') {
    refreshLibrary();
  }
}

// --- WebSocket Management ---
function initWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws`;

  const wsBadge = document.getElementById('ws-badge');
  const wsText = document.getElementById('ws-text');

  try {
    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
      wsBadge.className = 'flex items-center space-x-1.5 px-2.5 py-1 rounded-md text-xs font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/20';
      wsText.innerText = 'Live';
    };

    state.ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        handleWsEvent(payload);
      } catch (err) {
        console.error('Error parsing WS message:', err);
      }
    };

    state.ws.onclose = () => {
      wsBadge.className = 'flex items-center space-x-1.5 px-2.5 py-1 rounded-md text-xs font-mono bg-amber-500/10 text-amber-400 border border-amber-500/20';
      wsText.innerText = 'Reconnecting...';
      setTimeout(initWebSocket, 3000);
    };

    state.ws.onerror = () => {
      state.ws.close();
    };
  } catch (e) {
    console.error('WebSocket connection error:', e);
  }
}

function handleWsEvent(msg) {
  if (msg.event === 'initial_state') {
    state.jobs = msg.data.jobs || [];
    state.diagnostics = msg.data.diagnostics || {};
    state.config = msg.data.config || {};
    renderSystemDiagnostics(state.diagnostics);
    renderJobs();
    updateStats();
  } else if (msg.event === 'queue_batch_added') {
    const newJobs = msg.data || [];
    newJobs.forEach(nj => {
      const idx = state.jobs.findIndex(j => j.id === nj.id);
      if (idx >= 0) state.jobs[idx] = nj;
      else state.jobs.push(nj);
    });
    renderJobs();
    updateStats();
    showToast(`Added ${newJobs.length} tracks to extraction queue`, 'info');
  } else if (msg.event === 'job_updated') {
    const updatedJob = msg.data;
    const idx = state.jobs.findIndex(j => j.id === updatedJob.id);
    if (idx >= 0) {
      state.jobs[idx] = updatedJob;
    } else {
      state.jobs.push(updatedJob);
    }
    renderSingleJob(updatedJob);
    updateStats();

    if (updatedJob.stage === 'Completed') {
      refreshLibrary();
    }
  } else if (msg.event === 'queue_cleared') {
    if (msg.data && msg.data.clear_all) {
      state.jobs = [];
    } else {
      state.jobs = state.jobs.filter(j => !['Completed', 'Failed', 'Cancelled'].includes(j.stage));
    }
    renderJobs();
    updateStats();
  }
}

// --- Initial API Fetch ---
async function loadInitialData() {
  try {
    const [statusRes, queueRes, configRes] = await Promise.all([
      fetch('/api/system-status').then(r => r.json()),
      fetch('/api/queue').then(r => r.json()),
      fetch('/api/config').then(r => r.json())
    ]);

    state.diagnostics = statusRes.diagnostics || {};
    state.jobs = queueRes.jobs || [];
    state.config = configRes || {};

    renderSystemDiagnostics(state.diagnostics);
    populateSettingsForm(state.config);
    renderJobs();
    updateStats();
  } catch (err) {
    console.error('Error fetching initial data:', err);
  }
}

// --- Diagnostics Rendering ---
function renderSystemDiagnostics(diag) {
  const statusPill = document.getElementById('system-status-pill');
  const statusDot = document.getElementById('status-dot');
  const statusText = document.getElementById('status-text');

  const ffmpegEl = document.getElementById('diag-ffmpeg');
  const ffprobeEl = document.getElementById('diag-ffprobe');
  const lameEl = document.getElementById('diag-lame');
  const troubleBox = document.getElementById('troubleshooting-box');
  const troubleText = document.getElementById('troubleshooting-text');

  if (diag.ready) {
    statusDot.className = 'w-2 h-2 rounded-full bg-emerald-400 animate-pulse';
    statusText.innerText = 'FFmpeg Engine Ready';
    troubleBox.classList.add('hidden');
  } else {
    statusDot.className = 'w-2 h-2 rounded-full bg-rose-500 animate-pulse';
    statusText.innerText = 'Missing Dependencies';
    troubleBox.classList.remove('hidden');
    troubleText.innerHTML = (diag.troubleshooting || []).join('<br/>');
  }

  if (ffmpegEl && diag.ffmpeg) {
    ffmpegEl.innerText = diag.ffmpeg.available ? 'OK (Found in PATH)' : 'Missing';
    ffmpegEl.className = diag.ffmpeg.available ? 'font-mono text-emerald-400' : 'font-mono text-rose-400';
  }
  if (ffprobeEl && diag.ffprobe) {
    ffprobeEl.innerText = diag.ffprobe.available ? 'OK (Found in PATH)' : 'Missing';
    ffprobeEl.className = diag.ffprobe.available ? 'font-mono text-emerald-400' : 'font-mono text-rose-400';
  }
  if (lameEl && diag.libmp3lame) {
    lameEl.innerText = diag.libmp3lame.available ? 'libmp3lame (VBR V0 Supported)' : 'Missing';
    lameEl.className = diag.libmp3lame.available ? 'font-mono text-emerald-400' : 'font-mono text-rose-400';
  }
}

// --- Ingestion Event Listeners ---
function setupEventListeners() {
  const textarea = document.getElementById('raw-tracks-input');
  const lineCountPreview = document.getElementById('line-count-preview');
  const dropZone = document.getElementById('drop-zone');
  const fileInput = document.getElementById('file-upload-input');

  textarea.addEventListener('input', () => {
    const lines = textarea.value.split('\n').filter(l => l.trim() && !l.trim().startsWith('#'));
    lineCountPreview.innerText = `${lines.length} track${lines.length === 1 ? '' : 's'} detected`;
  });

  // Drag & Drop
  dropZone.addEventListener('click', () => fileInput.click());

  dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('drop-zone-active');
  });

  dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('drop-zone-active');
  });

  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('drop-zone-active');
    if (e.dataTransfer.files.length > 0) {
      handleFileUpload(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
      handleFileUpload(e.target.files[0]);
    }
  });

  // Global Audio element listeners
  const audioEl = document.getElementById('global-audio-element');
  audioEl.addEventListener('timeupdate', () => {
    const current = audioEl.currentTime || 0;
    const duration = audioEl.duration || 0;
    document.getElementById('player-current-time').innerText = formatTime(current);
    document.getElementById('player-total-time').innerText = formatTime(duration);
    const pct = duration > 0 ? (current / duration) * 100 : 0;
    document.getElementById('player-progress-fill').style.width = `${pct}%`;
  });

  audioEl.addEventListener('ended', () => {
    state.isPlaying = false;
    updatePlayPauseButtonUI();
  });
}

function clearInput() {
  const textarea = document.getElementById('raw-tracks-input');
  textarea.value = '';
  document.getElementById('line-count-preview').innerText = '0 tracks detected';
}

async function submitQueue() {
  const textarea = document.getElementById('raw-tracks-input');
  const text = textarea.value.trim();
  if (!text) {
    showToast('Please paste at least one track title or URL', 'error');
    return;
  }

  const btn = document.getElementById('submit-queue-btn');
  btn.disabled = true;
  btn.classList.add('opacity-50');

  try {
    const res = await fetch('/api/queue/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ raw_text: text })
    });

    const data = await res.json();
    if (res.ok) {
      clearInput();
      showToast(data.message, 'success');
    } else {
      showToast(data.detail || 'Failed to queue tracks', 'error');
    }
  } catch (err) {
    showToast('Network error while queuing tracks', 'error');
  } finally {
    btn.disabled = false;
    btn.classList.remove('opacity-50');
  }
}

async function handleFileUpload(file) {
  if (!file.name.endsWith('.txt') && !file.name.endsWith('.csv')) {
    showToast('Please upload a .txt or .csv file', 'error');
    return;
  }

  const formData = new FormData();
  formData.append('file', file);

  showToast(`Uploading and parsing ${file.name}...`, 'info');

  try {
    const res = await fetch('/api/queue/upload', {
      method: 'POST',
      body: formData
    });

    const data = await res.json();
    if (res.ok) {
      showToast(data.message, 'success');
    } else {
      showToast(data.detail || 'File parsing failed', 'error');
    }
  } catch (err) {
    showToast('File upload error', 'error');
  }
}

// --- Queue & Job Rendering ---
function renderJobs() {
  const container = document.getElementById('job-list-container');
  const emptyPlaceholder = document.getElementById('empty-queue-placeholder');

  if (state.jobs.length === 0) {
    container.innerHTML = '';
    container.appendChild(emptyPlaceholder);
    return;
  }

  container.innerHTML = '';
  state.jobs.forEach(job => {
    container.appendChild(createJobElement(job));
  });
}

function renderSingleJob(job) {
  const existing = document.getElementById(`job-row-${job.id}`);
  const container = document.getElementById('job-list-container');
  const emptyPlaceholder = document.getElementById('empty-queue-placeholder');

  if (emptyPlaceholder && emptyPlaceholder.parentElement === container) {
    container.removeChild(emptyPlaceholder);
  }

  const newEl = createJobElement(job);
  if (existing) {
    existing.replaceWith(newEl);
  } else {
    container.prepend(newEl);
  }
}

function getStageBadgeConfig(stage) {
  switch (stage) {
    case 'Queued':
      return {
        bg: 'bg-slate-800/80 text-slate-300 border-slate-700',
        icon: 'fa-solid fa-clock'
      };
    case 'Resolving Stream':
      return {
        bg: 'bg-purple-950/40 text-purple-300 border-purple-800/40 animate-pulse',
        icon: 'fa-solid fa-satellite-dish'
      };
    case 'Downloading':
      return {
        bg: 'bg-indigo-950/40 text-indigo-300 border-indigo-800/40',
        icon: 'fa-solid fa-arrow-down animate-bounce'
      };
    case 'Transcoding (FFmpeg)':
      return {
        bg: 'bg-amber-950/40 text-amber-300 border-amber-800/40',
        icon: 'fa-solid fa-gear fa-spin'
      };
    case 'Tagging ID3':
      return {
        bg: 'bg-cyan-950/40 text-cyan-300 border-cyan-800/40',
        icon: 'fa-solid fa-tags'
      };
    case 'Completed':
      return {
        bg: 'bg-emerald-950/40 text-emerald-300 border-emerald-800/40',
        icon: 'fa-solid fa-circle-check text-emerald-400'
      };
    case 'Failed':
      return {
        bg: 'bg-rose-950/40 text-rose-300 border-rose-800/40',
        icon: 'fa-solid fa-circle-xmark text-rose-400'
      };
    case 'Cancelled':
      return {
        bg: 'bg-slate-900 text-slate-400 border-slate-800',
        icon: 'fa-solid fa-ban'
      };
    default:
      return {
        bg: 'bg-slate-800 text-slate-300 border-slate-700',
        icon: 'fa-solid fa-circle-dot'
      };
  }
}

function createJobElement(job) {
  const div = document.createElement('div');
  div.id = `job-row-${job.id}`;
  div.className = 'p-4 hover:bg-dark-hover/40 transition flex flex-col space-y-3';

  const badgeConfig = getStageBadgeConfig(job.stage);
  const isTerminal = ['Completed', 'Failed', 'Cancelled'].includes(job.stage);
  const isRunning = !isTerminal && job.stage !== 'Queued';

  // Determine cover/thumbnail source
  const artworkUrl = job.thumbnail_url || (job.relative_path ? `/api/library/cover?path=${encodeURIComponent(job.relative_path)}` : '');

  div.innerHTML = `
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
      <div class="flex items-start space-x-3.5">
        <!-- Track Thumbnail / Cover Artwork -->
        <div class="w-11 h-11 rounded-xl bg-dark-bg border border-dark-border flex items-center justify-center text-slate-400 shrink-0 mt-0.5 overflow-hidden shadow-inner relative">
          <img 
            src="${artworkUrl}" 
            class="w-full h-full object-cover ${artworkUrl ? '' : 'hidden'}" 
            onerror="this.classList.add('hidden'); this.nextElementSibling.classList.remove('hidden');" 
          />
          <i class="fa-solid fa-music text-xs ${artworkUrl ? 'hidden' : ''}"></i>
        </div>
        <div>
          <div class="flex items-center space-x-2">
            <h4 class="text-sm font-bold text-slate-100">${escapeHtml(job.track.title)}</h4>
            <span class="text-xs text-slate-400 font-medium">by <strong class="text-slate-300">${escapeHtml(job.track.artist || 'Unknown')}</strong></span>
            ${job.track.album && job.track.album !== 'Single' ? `<span class="px-1.5 py-0.2 text-[10px] bg-dark-bg text-slate-400 rounded border border-dark-border">(${escapeHtml(job.track.album)})</span>` : ''}
          </div>
          <div class="flex items-center space-x-3 text-[11px] text-slate-400 mt-0.5">
            <span class="font-mono text-slate-500">${escapeHtml(job.detail || '')}</span>
            ${job.file_size_formatted ? `<span class="text-emerald-400 font-mono font-semibold">${job.file_size_formatted}</span>` : ''}
          </div>
        </div>
      </div>

      <!-- Badge & Action Buttons -->
      <div class="flex items-center space-x-2.5 self-end sm:self-center shrink-0">
        <!-- Stage Badge -->
        <span class="px-2.5 py-1 rounded-md text-xs font-semibold border flex items-center space-x-1.5 ${badgeConfig.bg}">
          <i class="${badgeConfig.icon} text-[11px]"></i>
          <span>${job.stage}</span>
        </span>

        <!-- Go to Library Button on Completed -->
        ${job.stage === 'Completed' ? `
          <button onclick="switchTab('library')" class="px-3 py-1.5 rounded-lg bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-300 border border-emerald-500/30 text-xs font-semibold flex items-center space-x-1.5 transition" title="Go to Music Library">
            <i class="fa-solid fa-folder-music text-xs"></i>
            <span>Library</span>
          </button>
        ` : ''}

        <!-- Retry Button (Safe ID lookup) -->
        ${['Failed', 'Cancelled', 'Completed'].includes(job.stage) ? `
          <button onclick="openRetryModal('${job.id}')" class="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs transition" title="Retry / Override Search">
            <i class="fa-solid fa-arrows-rotate"></i>
          </button>
        ` : ''}

        <!-- Cancel Button -->
        ${!isTerminal ? `
          <button onclick="cancelJob('${job.id}')" class="p-1.5 rounded-lg bg-rose-950/40 hover:bg-rose-900/50 text-rose-300 border border-rose-800/40 text-xs transition" title="Cancel Extraction">
            <i class="fa-solid fa-stop"></i>
          </button>
        ` : ''}
      </div>
    </div>

    <!-- Progress Bar & Speed / ETA Status -->
    ${!['Queued', 'Cancelled'].includes(job.stage) ? `
      <div class="space-y-1">
        <div class="w-full bg-dark-bg h-1.5 rounded-full overflow-hidden border border-dark-border">
          <div 
            class="h-full bg-gradient-to-r ${job.stage === 'Completed' ? 'from-emerald-500 to-teal-400' : job.stage === 'Failed' ? 'from-rose-600 to-red-500' : 'from-brand-500 to-indigo-400 progress-bar-animated'} transition-all duration-300" 
            style="width: ${job.progress_percent}%"
          ></div>
        </div>
        ${isRunning ? `
          <div class="flex justify-between text-[10px] font-mono text-slate-400">
            <span>Speed: <strong class="text-slate-300">${job.speed_str}</strong></span>
            <span>Progress: <strong class="text-slate-300">${job.progress_percent}%</strong></span>
            <span>ETA: <strong class="text-slate-300">${job.eta_str}</strong></span>
          </div>
        ` : ''}
      </div>
    ` : ''}
  `;

  return div;
}

function updateStats() {
  const total = state.jobs.length;
  const running = state.jobs.filter(j => !['Queued', 'Completed', 'Failed', 'Cancelled'].includes(j.stage)).length;
  const completed = state.jobs.filter(j => j.stage === 'Completed').length;
  const failed = state.jobs.filter(j => j.stage === 'Failed').length;

  document.getElementById('stat-total').innerText = total;
  document.getElementById('stat-running').innerText = running;
  document.getElementById('stat-completed').innerText = completed;
  document.getElementById('stat-failed').innerText = failed;
  document.getElementById('queue-badge-count').innerText = total;
}

// --- Job Actions ---
async function cancelJob(jobId) {
  try {
    const res = await fetch(`/api/queue/${jobId}/cancel`, { method: 'POST' });
    if (res.ok) {
      showToast('Extraction job cancelled', 'info');
    }
  } catch (err) {
    showToast('Failed to cancel job', 'error');
  }
}

async function clearQueue(clearAll) {
  if (clearAll) {
    state.jobs = [];
  } else {
    state.jobs = state.jobs.filter(j => !['Completed', 'Failed', 'Cancelled'].includes(j.stage));
  }
  renderJobs();
  updateStats();

  try {
    await fetch(`/api/queue/clear?clear_all=${clearAll ? 'true' : 'false'}`, { method: 'POST' });
    showToast(clearAll ? 'Cleared entire queue' : 'Cleared finished jobs', 'info');
  } catch (err) {
    showToast('Failed to clear queue', 'error');
  }
}

// --- Retry Modal ---
function openRetryModal(jobId) {
  const job = state.jobs.find(j => j.id === jobId);
  const defaultQuery = job ? (job.track.custom_search_override || (job.track.artist ? `${job.track.artist} - ${job.track.title}` : job.track.title)) : '';
  
  document.getElementById('modal-job-id').value = jobId;
  document.getElementById('modal-override-query').value = defaultQuery || '';
  document.getElementById('retry-modal').classList.remove('hidden');
}

function closeRetryModal() {
  document.getElementById('retry-modal').classList.add('hidden');
}

async function submitRetryWithOverride() {
  const jobId = document.getElementById('modal-job-id').value;
  const query = document.getElementById('modal-override-query').value.trim();

  try {
    const res = await fetch(`/api/queue/${jobId}/retry`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ custom_override: query || null })
    });

    if (res.ok) {
      closeRetryModal();
      showToast('Job re-enqueued with override query', 'success');
    } else {
      showToast('Failed to retry job', 'error');
    }
  } catch (err) {
    showToast('Network error during retry', 'error');
  }
}

// --- Library Management ---
async function refreshLibrary() {
  try {
    const res = await fetch('/api/library');
    const data = await res.json();
    state.library = data.tracks || [];

    const badge = document.getElementById('library-badge-count');
    if (badge) badge.innerText = data.total_tracks || 0;

    renderLibrary(state.library);
  } catch (err) {
    console.error('Error fetching library:', err);
  }
}

function renderLibrary(tracks) {
  const container = document.getElementById('library-container');
  const empty = document.getElementById('empty-library-placeholder');

  if (tracks.length === 0) {
    container.innerHTML = '';
    container.appendChild(empty);
    return;
  }

  container.innerHTML = '';
  tracks.forEach(track => {
    const div = document.createElement('div');
    // Strong hover outline & shadow, clickable whole card
    div.className = 'p-3.5 rounded-2xl bg-dark-bg/60 border border-dark-border hover:border-brand-500 hover:shadow-xl hover:shadow-brand-500/10 hover:bg-dark-hover/80 transition-all duration-200 cursor-pointer flex items-center justify-between group select-none';

    // Click on the song card itself triggers playback
    div.onclick = (e) => {
      if (!e.target.closest('.no-card-click')) {
        playAudioStream(track.relative_path, track.title, track.artist, track.cover_url);
      }
    };

    div.innerHTML = `
      <div class="flex items-center space-x-3.5">
        <!-- Album Art Thumbnail with Hover Play -->
        <div class="w-12 h-12 rounded-xl bg-dark-bg border border-dark-border flex items-center justify-center text-slate-400 overflow-hidden shrink-0 shadow-inner relative group-hover:border-brand-500/50 transition">
          <img src="${track.cover_url}" class="w-full h-full object-cover" onerror="this.classList.add('hidden'); this.nextElementSibling.classList.remove('hidden');" />
          <i class="fa-solid fa-music text-sm hidden"></i>
          <div class="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 flex items-center justify-center transition">
            <i class="fa-solid fa-play text-white text-xs"></i>
          </div>
        </div>

        <div>
          <div class="text-sm font-bold text-slate-100 group-hover:text-brand-300 transition">${escapeHtml(track.title)}</div>
          <div class="text-xs text-slate-400">${escapeHtml(track.artist)} • <span class="text-slate-500">${escapeHtml(track.album)}</span></div>
        </div>
      </div>

      <div class="flex items-center space-x-3 text-xs font-mono text-slate-400">
        <span>${track.duration_formatted}</span>
        <span class="text-emerald-400 font-semibold">${track.size_mb} MB</span>
        
        <!-- Play Button -->
        <button onclick="event.stopPropagation(); playAudioStream('${escapeHtml(track.relative_path)}', '${escapeHtml(track.title)}', '${escapeHtml(track.artist)}', '${track.cover_url}')" class="no-card-click p-2 rounded-xl bg-brand-600/20 hover:bg-brand-600/40 text-brand-300 border border-brand-500/30 transition" title="Play Track">
          <i class="fa-solid fa-play text-xs"></i>
        </button>

        <!-- Delete Button with Warning Confirmation -->
        <button onclick="event.stopPropagation(); openDeleteModal('${escapeHtml(track.relative_path)}', '${escapeHtml(track.title)}', '${escapeHtml(track.artist)}')" class="no-card-click p-2 rounded-xl bg-slate-800 hover:bg-rose-950/60 text-slate-400 hover:text-rose-300 hover:border-rose-800/50 border border-transparent transition" title="Delete Track">
          <i class="fa-regular fa-trash-can text-xs"></i>
        </button>
      </div>
    `;
    container.appendChild(div);
  });
}

function filterLibrary() {
  const query = document.getElementById('library-search-input').value.toLowerCase();
  const filtered = state.library.filter(t => 
    t.title.toLowerCase().includes(query) ||
    t.artist.toLowerCase().includes(query) ||
    t.album.toLowerCase().includes(query)
  );
  renderLibrary(filtered);
}

// --- Delete Modal Handlers ---
function openDeleteModal(relPath, title, artist) {
  document.getElementById('delete-modal-rel-path').value = relPath;
  document.getElementById('delete-modal-track-name').innerText = `${artist} - ${title}`;
  document.getElementById('delete-modal-path').innerText = relPath;
  document.getElementById('delete-modal').classList.remove('hidden');
}

function closeDeleteModal() {
  document.getElementById('delete-modal').classList.add('hidden');
}

async function confirmDeleteTrack() {
  const relPath = document.getElementById('delete-modal-rel-path').value;
  if (!relPath) return;

  try {
    const res = await fetch(`/api/library?path=${encodeURIComponent(relPath)}`, {
      method: 'DELETE'
    });
    const data = await res.json();
    if (res.ok) {
      closeDeleteModal();
      showToast(data.message || 'Track deleted', 'success');
      refreshLibrary();
    } else {
      showToast(data.detail || 'Failed to delete track', 'error');
    }
  } catch (err) {
    showToast('Network error while deleting track', 'error');
  }
}

async function openOutputFolder() {
  try {
    const res = await fetch('/api/library/open', { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      showToast('Opened output folder', 'success');
    } else {
      showToast(`Folder location: ${data.path}`, 'info');
    }
  } catch (err) {
    showToast('Failed to open folder', 'error');
  }
}

// --- Audio Player ---
function playAudioStream(relativePath, title, artist, thumbUrl) {
  const playerBar = document.getElementById('audio-player-bar');
  const audioEl = document.getElementById('global-audio-element');

  playerBar.classList.remove('hidden');
  document.getElementById('player-track-title').innerText = title || 'Unknown Title';
  document.getElementById('player-track-artist').innerText = artist || 'Unknown Artist';

  const thumbImg = document.getElementById('player-thumb-img');
  const thumbIcon = document.getElementById('player-thumb-icon');
  if (thumbUrl) {
    thumbImg.src = thumbUrl;
    thumbImg.classList.remove('hidden');
    thumbIcon.classList.add('hidden');
  } else {
    thumbImg.classList.add('hidden');
    thumbIcon.classList.remove('hidden');
  }

  audioEl.src = `/api/library/stream?path=${encodeURIComponent(relativePath)}`;
  audioEl.play().then(() => {
    state.isPlaying = true;
    updatePlayPauseButtonUI();
  }).catch(err => {
    console.warn('Auto-play blocked or audio load error:', err);
  });
}

function togglePlayPause() {
  const audioEl = document.getElementById('global-audio-element');
  if (!audioEl.src) return;

  if (audioEl.paused) {
    audioEl.play();
    state.isPlaying = true;
  } else {
    audioEl.pause();
    state.isPlaying = false;
  }
  updatePlayPauseButtonUI();
}

function updatePlayPauseButtonUI() {
  const icon = document.getElementById('player-play-icon');
  if (state.isPlaying) {
    icon.className = 'fa-solid fa-pause';
  } else {
    icon.className = 'fa-solid fa-play ml-0.5';
  }
}

function seekAudio(delta) {
  const audioEl = document.getElementById('global-audio-element');
  if (audioEl.duration) {
    audioEl.currentTime = Math.max(0, Math.min(audioEl.duration, audioEl.currentTime + delta));
  }
}

function handleSeekbarClick(e) {
  const audioEl = document.getElementById('global-audio-element');
  if (!audioEl.duration) return;

  const rect = e.currentTarget.getBoundingClientRect();
  const clickX = e.clientX - rect.left;
  const ratio = clickX / rect.width;
  audioEl.currentTime = ratio * audioEl.duration;
}

function setAudioVolume(val) {
  const audioEl = document.getElementById('global-audio-element');
  audioEl.volume = parseFloat(val);
}

function closeAudioPlayer() {
  const audioEl = document.getElementById('global-audio-element');
  audioEl.pause();
  state.isPlaying = false;
  document.getElementById('audio-player-bar').classList.add('hidden');
}

// --- Settings Form & Quick Toggles ---
function populateSettingsForm(cfg) {
  document.getElementById('setting-output-dir').value = cfg.output_dir || '';
  document.getElementById('setting-min-jitter').value = cfg.min_jitter_seconds || 2.0;
  document.getElementById('setting-max-jitter').value = cfg.max_jitter_seconds || 5.0;
  document.getElementById('setting-concurrency').value = cfg.max_concurrent_workers || 2;
  
  const organizeFolders = cfg.organize_by_artist !== undefined ? cfg.organize_by_artist : true;
  const settingCheck = document.getElementById('setting-organize-folders');
  const quickCheck = document.getElementById('quick-toggle-organize');
  
  if (settingCheck) settingCheck.checked = organizeFolders;
  if (quickCheck) quickCheck.checked = organizeFolders;
}

async function toggleQuickOrganize(isChecked) {
  const settingCheck = document.getElementById('setting-organize-folders');
  if (settingCheck) settingCheck.checked = isChecked;

  try {
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ organize_by_artist: isChecked })
    });
    if (res.ok) {
      showToast(isChecked ? 'Organizing into Artist folders enabled' : 'Flat folder download enabled', 'info');
    }
  } catch (err) {
    console.error('Failed to update organize setting:', err);
  }
}

async function saveSettings() {
  const organizeChecked = document.getElementById('setting-organize-folders').checked;
  const quickCheck = document.getElementById('quick-toggle-organize');
  if (quickCheck) quickCheck.checked = organizeChecked;

  const payload = {
    output_dir: document.getElementById('setting-output-dir').value,
    min_jitter_seconds: parseFloat(document.getElementById('setting-min-jitter').value),
    max_jitter_seconds: parseFloat(document.getElementById('setting-max-jitter').value),
    max_concurrent_workers: parseInt(document.getElementById('setting-concurrency').value, 10),
    organize_by_artist: organizeChecked
  };

  try {
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (res.ok) {
      showToast('Settings saved successfully', 'success');
      state.config = data.config;
    } else {
      showToast('Failed to save settings', 'error');
    }
  } catch (err) {
    showToast('Network error while saving settings', 'error');
  }
}

// --- Utilities ---
function formatTime(seconds) {
  if (isNaN(seconds) || seconds < 0) return '0:00';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs < 10 ? '0' : ''}${secs}`;
}

function escapeHtml(text) {
  if (!text) return '';
  const div = document.createElement('div');
  div.innerText = text;
  return div.innerHTML;
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  
  let bgClass = 'bg-slate-800 border-slate-700 text-slate-100';
  let icon = 'fa-solid fa-circle-info text-indigo-400';

  if (type === 'success') {
    bgClass = 'bg-emerald-950/90 border-emerald-700/50 text-emerald-100';
    icon = 'fa-solid fa-circle-check text-emerald-400';
  } else if (type === 'error') {
    bgClass = 'bg-rose-950/90 border-rose-700/50 text-rose-100';
    icon = 'fa-solid fa-triangle-exclamation text-rose-400';
  }

  toast.className = `flex items-center space-x-2.5 px-4 py-3 rounded-xl border shadow-xl text-xs font-medium transition-all transform duration-300 pointer-events-auto backdrop-blur-md ${bgClass}`;
  toast.innerHTML = `
    <i class="${icon} text-sm"></i>
    <span>${escapeHtml(message)}</span>
  `;

  container.appendChild(toast);

  setTimeout(() => {
    toast.classList.add('opacity-0', 'translate-x-4');
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}
