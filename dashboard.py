DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Code Reviewer — Дашборд</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0d1117; color: #e6edf3; min-height: 100vh; padding: 32px 16px; }
  h1 { font-size: 24px; margin-bottom: 8px; }
  .subtitle { color: #8b949e; margin-bottom: 32px; font-size: 14px; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 12px;
          padding: 24px; margin-bottom: 24px; max-width: 800px; margin-inline: auto; }
  .card h2 { font-size: 16px; margin-bottom: 16px; color: #58a6ff; }
  select { width: 100%; padding: 10px 12px; background: #0d1117; border: 1px solid #30363d;
           border-radius: 8px; color: #e6edf3; font-size: 14px; margin-bottom: 16px; }
  .record-btn { display: flex; align-items: center; gap: 10px; padding: 12px 20px;
                border-radius: 8px; border: none; font-size: 15px; cursor: pointer;
                background: #238636; color: white; transition: background 0.2s; }
  .record-btn.recording { background: #da3633; }
  .record-btn:hover { opacity: 0.85; }
  textarea { width: 100%; min-height: 100px; padding: 12px; background: #0d1117;
             border: 1px solid #30363d; border-radius: 8px; color: #e6edf3;
             font-size: 14px; resize: vertical; margin-top: 16px; }
  .send-btn { margin-top: 12px; padding: 10px 24px; background: #1f6feb; color: white;
              border: none; border-radius: 8px; font-size: 15px; cursor: pointer; }
  .send-btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .status { margin-top: 12px; font-size: 13px; color: #8b949e; min-height: 20px; }
  .status.success { color: #3fb950; }
  .status.error { color: #f85149; }
  .review-item { border-bottom: 1px solid #21262d; padding: 16px 0; }
  .review-item:last-child { border-bottom: none; }
  .review-meta { font-size: 12px; color: #8b949e; margin-bottom: 6px; }
  .review-text { font-size: 14px; line-height: 1.6; white-space: pre-wrap; }
  .empty { color: #8b949e; font-size: 14px; text-align: center; padding: 24px 0; }
  .dot { width: 10px; height: 10px; border-radius: 50%; background: #da3633;
         animation: pulse 1s infinite; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }
</style>
</head>
<body>
<div style="max-width:800px;margin:0 auto;">
  <h1>🤖 AI Code Reviewer</h1>
  <p class="subtitle">Панель преподавателя</p>

  <!-- Голосовой комментарий -->
  <div class="card">
    <h2>🎤 Добавить голосовой комментарий к ревью</h2>

    <label style="font-size:13px;color:#8b949e;display:block;margin-bottom:6px;">
      Выберите PR:
    </label>
    <select id="prSelect">
      <option value="">— загрузка... —</option>
    </select>

    <button class="record-btn" id="recordBtn" onclick="toggleRecording()">
      <span id="btnIcon">🎤</span>
      <span id="btnText">Начать запись</span>
    </button>

    <textarea id="transcriptArea" placeholder="Здесь появится расшифровка записи. Можно редактировать перед отправкой..."></textarea>

    <br>
    <button class="send-btn" id="sendBtn" onclick="sendVoiceReview()" disabled>
      Отправить комментарий в PR
    </button>
    <div class="status" id="status"></div>
  </div>

  <!-- Последние ревью -->
  <div class="card">
    <h2>📋 Последние автоматические ревью</h2>
    <div id="reviewsList"><p class="empty">Ревью ещё не поступали</p></div>
  </div>
</div>

<script>
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;

window.onload = () => { loadReviews(); };

async function loadReviews() {
  const resp = await fetch('/api/reviews');
  const data = await resp.json();
  const list = document.getElementById('reviewsList');
  const select = document.getElementById('prSelect');

  if (data.length === 0) {
    list.innerHTML = '<p class="empty">Ревью ещё не поступали</p>';
    select.innerHTML = '<option value="">— нет доступных PR —</option>';
    return;
  }

  select.innerHTML = data.map(r =>
    `<option value="${r.repo}|${r.pr_number}|${r.installation_id}">
      ${r.repo} — PR #${r.pr_number}
    </option>`
  ).join('');

  list.innerHTML = data.map(r => `
    <div class="review-item">
      <div class="review-meta">${r.repo} · PR #${r.pr_number} · ${r.time}</div>
      <div class="review-text">${r.review.substring(0, 300)}...</div>
    </div>
  `).join('');
}

async function toggleRecording() {
  if (!isRecording) { await startRecording(); } else { stopRecording(); }
}

async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = new MediaRecorder(stream);
    audioChunks = [];

    mediaRecorder.ondataavailable = e => audioChunks.push(e.data);
    mediaRecorder.onstop = async () => {
      const blob = new Blob(audioChunks, { type: 'audio/webm' });
      await transcribeAudio(blob);
    };

    mediaRecorder.start();
    isRecording = true;
    document.getElementById('recordBtn').classList.add('recording');
    document.getElementById('btnIcon').textContent = '⏹';
    document.getElementById('btnText').textContent = 'Остановить запись';
    setStatus('🔴 Идёт запись...', '');
  } catch (e) {
    setStatus('Ошибка доступа к микрофону: ' + e.message, 'error');
  }
}

function stopRecording() {
  mediaRecorder.stop();
  isRecording = false;
  document.getElementById('recordBtn').classList.remove('recording');
  document.getElementById('btnIcon').textContent = '🎤';
  document.getElementById('btnText').textContent = 'Начать запись';
  setStatus('⏳ Расшифровываю...', '');
}

async function transcribeAudio(blob) {
  const formData = new FormData();
  formData.append('audio', blob, 'recording.webm');

  const resp = await fetch('/transcribe', { method: 'POST', body: formData });
  const data = await resp.json();

  if (data.text) {
    document.getElementById('transcriptArea').value = data.text;
    document.getElementById('sendBtn').disabled = false;
    setStatus('✅ Расшифровка готова. Проверьте текст и отправьте.', 'success');
  } else {
    setStatus('Ошибка расшифровки: ' + (data.error || 'неизвестно'), 'error');
  }
}

async function sendVoiceReview() {
  const selected = document.getElementById('prSelect').value;
  const text = document.getElementById('transcriptArea').value.trim();

  if (!selected || !text) {
    setStatus('Выберите PR и запишите комментарий', 'error');
    return;
  }

  const [repo, prNumber, installationId] = selected.split('|');
  document.getElementById('sendBtn').disabled = true;
  setStatus('⏳ Генерирую комментарий в стиле преподавателя...', '');

  const resp = await fetch('/api/voice-review', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ repo, pr_number: parseInt(prNumber),
                           installation_id: parseInt(installationId),
                           teacher_comment: text })
  });

  const data = await resp.json();
  if (data.success) {
    setStatus('✅ Комментарий отправлен в PR!', 'success');
    document.getElementById('transcriptArea').value = '';
  } else {
    setStatus('Ошибка: ' + (data.error || 'неизвестно'), 'error');
    document.getElementById('sendBtn').disabled = false;
  }
}

function setStatus(msg, cls) {
  const el = document.getElementById('status');
  el.textContent = msg;
  el.className = 'status ' + cls;
}
</script>
</body>
</html>
"""
