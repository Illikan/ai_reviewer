from config import ai_client, MODEL_NAME


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


async def generate_review(task_description: str, code_changes: str, style: str) -> str:
    prompt = build_prompt(task_description, code_changes, style)
    response = await ai_client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content


async def generate_teacher_comment(teacher_comment: str, review_text: str) -> str:
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
    return response.choices[0].message.content
