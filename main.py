import os
import time
import hmac
import hashlib
import requests
import jwt
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Header, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse
import uvicorn
from github import Github
from openai import AsyncOpenAI

load_dotenv()

app = FastAPI()

GITHUB_APP_ID = os.getenv("GITHUB_APP_ID")
GITHUB_PRIVATE_KEY = os.getenv("GITHUB_PRIVATE_KEY").replace("\\n", "\n")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODEL_NAME = os.getenv("MODEL_NAME", "meta-llama/llama-4-scout:free")

ai_client = AsyncOpenAI(
    api_key=OPENAI_API_KEY,
    base_url="https://openrouter.ai/api/v1"
)

groq_client = AsyncOpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1"
)

# Хранилище последних ревью (в памяти, для MVP)
recent_reviews = []


def verify_signature(payload_bytes: bytes, signature: str) -> bool:
    if not GITHUB_WEBHOOK_SECRET:
        return True
    mac = hmac.new(GITHUB_WEBHOOK_SECRET.encode(), payload_bytes, hashlib.sha256)
    expected = f"sha256={mac.hexdigest()}"
    return hmac.compare_digest(expected, signature or "")


def get_installation_token(installation_id: int) -> str:
    payload = {
        "iat": int(time.time()) - 60,
        "exp": int(time.time()) + 540,
        "iss": GITHUB_APP_ID
    }
    encoded_jwt = jwt.encode(payload, GITHUB_PRIVATE_KEY, algorithm="RS256")
    resp = requests.post(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        headers={
            "Authorization": f"Bearer {encoded_jwt}",
            "Accept": "application/vnd.github+json"
        }
    )
    resp.raise_for_status()
    return resp.json()["token"]


def get_review_style(pr) -> str:
    labels = [label.name for label in pr.labels]
    if "review:detailed" in labels:
        return "detailed"
    return "short"


def build_prompt(task_description: str, code_changes: str, style: str) -> str:
    if style == "detailed":
        instruction = """ИНСТРУКЦИЯ (развёрнутый режим):
1. Подробно проанализируй, решает ли код поставленную задачу.
2. Разбери каждый файл отдельно.
3. Укажи все логические, синтаксические и стилистические ошибки с объяснением, почему это ошибка.
4. Предложи конкретные улучшения с примерами кода.
5. Дай итоговый вывод: ЗАЧТЕНО / НА ДОРАБОТКУ — и объясни почему."""
    else:
        instruction = """ИНСТРУКЦИЯ (лаконичный режим):
1. Одним абзацем: решает ли код задачу?
2. Перечисли только критические ошибки (если есть), без лишних деталей.
3. Итог одной строкой: ✅ ЗАЧТЕНО или ❌ НА ДОРАБОТКУ."""

    return f"""Ты — строгий AI-ассистент преподавателя по программированию.
Сделай code review для Pull Request студента.

ОПИСАНИЕ ЗАДАЧИ ОТ ПРЕПОДАВАТЕЛЯ:
{task_description}

ИЗМЕНЕНИЯ В КОДЕ (Git Diff):
{code_changes}

{instruction}

Отвечай на русском языке, используй Markdown."""


# ── Дашборд ──────────────────────────────────────────────────────────────────

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

// Загрузка списка PR и ревью при старте
window.onload = () => {
  loadReviews();
};

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

  // Заполняем список PR
  select.innerHTML = data.map(r =>
    `<option value="${r.repo}|${r.pr_number}|${r.installation_id}">
      ${r.repo} — PR #${r.pr_number}
    </option>`
  ).join('');

  // Заполняем список ревью
  list.innerHTML = data.map(r => `
    <div class="review-item">
      <div class="review-meta">${r.repo} · PR #${r.pr_number} · ${r.time}</div>
      <div class="review-text">${r.review.substring(0, 300)}...</div>
    </div>
  `).join('');
}

async function toggleRecording() {
  if (!isRecording) {
    await startRecording();
  } else {
    stopRecording();
  }
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
      stream.getTracks().forEach(t => t.stop());
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


# ── Эндпоинты ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse("<h2>AI Code Reviewer работает ✅ <a href='/dashboard'>→ Дашборд</a></h2>")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(DASHBOARD_HTML)


@app.get("/api/reviews")
async def get_reviews():
    return recent_reviews[-20:]  # последние 20


@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    """Принимает аудио, отправляет в Whisper через Groq, возвращает текст."""
    try:
        audio_bytes = await audio.read()
        transcription = await groq_client.audio.transcriptions.create(
            model="whisper-large-v3",
            file=(audio.filename, audio_bytes, audio.content_type),
            language="ru"
        )
        return {"text": transcription.text}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/voice-review")
async def voice_review(request: Request):
    """Берёт комментарий преподавателя + последнее ревью и постит стилизованный комментарий в PR."""
    data = await request.json()
    repo_name = data.get("repo")
    pr_number = data.get("pr_number")
    installation_id = data.get("installation_id")
    teacher_comment = data.get("teacher_comment")

    # Ищем последнее автоматическое ревью для этого PR
    last_review = next(
        (r for r in reversed(recent_reviews)
         if r["repo"] == repo_name and r["pr_number"] == pr_number),
        None
    )
    review_text = last_review["review"] if last_review else "Автоматическое ревью недоступно."

    try:
        token = get_installation_token(installation_id)
        repo = Github(token).get_repo(repo_name)
        pr = repo.get_pull(pr_number)

        prompt = f"""Ты помогаешь преподавателю написать комментарий к студенческому коду.

Вот автоматическое AI-ревью которое уже было сделано:
{review_text}

Вот что преподаватель хочет добавить от себя (надиктовано голосом):
{teacher_comment}

Задача: напиши финальный комментарий преподавателя в PR.
Используй стиль и интонацию его слов — если он говорил неформально, пиши неформально.
Учти автоматическое ревью но не копируй его — дополни своим взглядом.
Отвечай на русском языке, используй Markdown."""

        response = await ai_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}]
        )
        final_comment = response.choices[0].message.content

        pr.create_issue_comment(f"💬 **Комментарий преподавателя:**\n\n{final_comment}")
        return {"success": True}

    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/github-webhook")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(None),
    x_hub_signature_256: str = Header(None)
):
    payload_bytes = await request.body()

    if not verify_signature(payload_bytes, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid signature")

    if x_github_event == "ping":
        return {"message": "Pong!"}

    if x_github_event == "pull_request":
        payload = await request.json()
        action = payload.get("action")

        if action in ["opened", "synchronize", "labeled"]:
            repo_name = payload.get("repository", {}).get("full_name")
            pr_number = payload.get("pull_request", {}).get("number")
            installation_id = payload.get("installation", {}).get("id")

            try:
                token = get_installation_token(installation_id)
                repo = Github(token).get_repo(repo_name)
                pr = repo.get_pull(pr_number)

                task_description = pr.body or "Описание задачи отсутствует."

                files = pr.get_files()
                code_changes = ""
                for file in files:
                    if file.patch:
                        code_changes += f"\n--- Файл: {file.filename} ---\n{file.patch}\n"

                if not code_changes:
                    code_changes = "Изменений в коде не обнаружено."

                style = get_review_style(pr)
                style_label = "📋 Развёрнутый режим" if style == "detailed" else "⚡ Лаконичный режим"

                print(f">>> PR #{pr_number} | Стиль: {style} | Отправляю в AI...")

                prompt = build_prompt(task_description, code_changes, style)

                response = await ai_client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[{"role": "user", "content": prompt}]
                )
                ai_review = response.choices[0].message.content

                final_comment = (
                    f"🤖 **AI Code Review** | {style_label}\n\n"
                    f"{ai_review}\n\n"
                    f"---\n"
                    f"*Чтобы переключить режим: добавь лейбл `review:detailed` для развёрнутого ревью "
                    f"или убери его для лаконичного.*"
                )

                pr.create_issue_comment(final_comment)
                print(f">>> Ревью отправлено! Стиль: {style}")

                # Сохраняем ревью для дашборда
                from datetime import datetime
                recent_reviews.append({
                    "repo": repo_name,
                    "pr_number": pr_number,
                    "installation_id": installation_id,
                    "review": ai_review,
                    "time": datetime.now().strftime("%d.%m.%Y %H:%M")
                })

            except Exception as e:
                print(f"Ошибка: {e}")

            return {"message": "Processing started"}

    return {"message": "Event ignored"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)