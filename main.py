import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Header
import uvicorn
from github import Github
from openai import AsyncOpenAI

load_dotenv()

app = FastAPI()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

gh = Github(GITHUB_TOKEN)
ai_client = AsyncOpenAI(
    api_key=OPENAI_API_KEY,
    base_url="https://openrouter.ai/api/v1"
)


def get_review_style(pr) -> str:
    """Определяет стиль ревью по лейблам PR."""
    labels = [label.name for label in pr.labels]
    if "review:detailed" in labels:
        return "detailed"
    return "short"


def build_prompt(task_description: str, code_changes: str, style: str) -> str:
    """Собирает промпт в зависимости от стиля ревью."""

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


@app.post("/github-webhook")
async def github_webhook(request: Request, x_github_event: str = Header(None)):

    if x_github_event == "ping":
        return {"message": "Pong!"}

    if x_github_event == "pull_request":
        payload = await request.json()
        action = payload.get("action")

        # Реагируем на открытие, обновление PR, а также на добавление лейбла
        if action in ["opened", "synchronize", "labeled"]:
            repo_name = payload.get("repository", {}).get("full_name")
            pr_number = payload.get("pull_request", {}).get("number")

            try:
                repo = gh.get_repo(repo_name)
                pr = repo.get_pull(pr_number)

                task_description = pr.body or "Описание задачи отсутствует."

                files = pr.get_files()
                code_changes = ""
                for file in files:
                    if file.patch:  # patch может быть None для бинарных файлов
                        code_changes += f"\n--- Файл: {file.filename} ---\n{file.patch}\n"

                if not code_changes:
                    code_changes = "Изменений в коде не обнаружено."

                style = get_review_style(pr)
                style_label = "📋 Развёрнутый режим" if style == "detailed" else "⚡ Лаконичный режим"

                print(f">>> PR #{pr_number} | Стиль: {style} | Отправляю в AI...")

                prompt = build_prompt(task_description, code_changes, style)

                response = await ai_client.chat.completions.create(
                    model="meta-llama/llama-3-8b-instruct:free",
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

            except Exception as e:
                print(f"Ошибка: {e}")

            return {"message": "Processing started"}

    return {"message": "Event ignored"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
