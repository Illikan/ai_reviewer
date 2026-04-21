from datetime import datetime

import uvicorn
from fastapi import FastAPI, Request, Header, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse

from config import recent_reviews
from dashboard import DASHBOARD_HTML
from github_app import verify_signature, get_github_repo, get_review_style, get_pr_diff
from ai_review import generate_review, generate_teacher_comment
from voice import transcribe_audio

app = FastAPI()


# ── Основные страницы ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse("<h2>AI Code Reviewer работает ✅ <a href='/dashboard'>→ Дашборд</a></h2>")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(DASHBOARD_HTML)


# ── API ────────────────────────────────────────────────────────────────────────

@app.get("/api/reviews")
async def get_reviews():
    return recent_reviews[-20:]


@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    try:
        text = await transcribe_audio(audio)
        return {"text": text}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/voice-review")
async def voice_review(request: Request):
    data = await request.json()
    repo_name = data.get("repo")
    pr_number = data.get("pr_number")
    installation_id = data.get("installation_id")
    teacher_comment = data.get("teacher_comment")

    last_review = next(
        (r for r in reversed(recent_reviews)
         if r["repo"] == repo_name and r["pr_number"] == pr_number),
        None
    )
    review_text = last_review["review"] if last_review else "Автоматическое ревью недоступно."

    try:
        repo = get_github_repo(installation_id, repo_name)
        pr = repo.get_pull(pr_number)

        final_comment = await generate_teacher_comment(teacher_comment, review_text)
        pr.create_issue_comment(f"💬 **Комментарий преподавателя:**\n\n{final_comment}")
        return {"success": True}

    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Webhook ────────────────────────────────────────────────────────────────────

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
                repo = get_github_repo(installation_id, repo_name)
                pr = repo.get_pull(pr_number)

                task_description = pr.body or "Описание задачи отсутствует."
                code_changes = get_pr_diff(pr)
                style = get_review_style(pr)
                style_label = "📋 Развёрнутый режим" if style == "detailed" else "⚡ Лаконичный режим"

                print(f">>> PR #{pr_number} | Стиль: {style} | Отправляю в AI...")

                ai_review = await generate_review(task_description, code_changes, style)

                final_comment = (
                    f"🤖 **AI Code Review** | {style_label}\n\n"
                    f"{ai_review}\n\n"
                    f"---\n"
                    f"*Чтобы переключить режим: добавь лейбл `review:detailed` для развёрнутого ревью "
                    f"или убери его для лаконичного.*"
                )

                pr.create_issue_comment(final_comment)
                print(f">>> Ревью отправлено! Стиль: {style}")

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
