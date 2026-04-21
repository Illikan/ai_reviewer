from fastapi import UploadFile
from config import groq_client


async def transcribe_audio(audio: UploadFile) -> str:
    """Принимает аудио, отправляет в Whisper через Groq, возвращает текст."""
    audio_bytes = await audio.read()
    transcription = await groq_client.audio.transcriptions.create(
        model="whisper-large-v3",
        file=(audio.filename, audio_bytes, audio.content_type),
        language="ru"
    )
    return transcription.text
