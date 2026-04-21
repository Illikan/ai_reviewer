import time
import hmac
import hashlib
import requests
import jwt
from github import Github
from config import GITHUB_APP_ID, GITHUB_PRIVATE_KEY, GITHUB_WEBHOOK_SECRET


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


def get_github_repo(installation_id: int, repo_name: str):
    token = get_installation_token(installation_id)
    return Github(token).get_repo(repo_name)


def get_review_style(pr) -> str:
    labels = [label.name for label in pr.labels]
    if "review:detailed" in labels:
        return "detailed"
    return "short"


def get_pr_diff(pr) -> str:
    files = pr.get_files()
    code_changes = ""
    for file in files:
        if file.patch:
            code_changes += f"\n--- Файл: {file.filename} ---\n{file.patch}\n"
    return code_changes or "Изменений в коде не обнаружено."
