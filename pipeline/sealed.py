"""再利用条件のないソース（ティア2）の本文を、公開リポジトリに読める形で置かないための暗号化。

- 収集（GitHub Actions）は、リポジトリにある公開鍵（config/queue_cert.pem）で本文を暗号化して保存する。
  公開鍵では暗号化しかできないので、リポジトリを見た人が本文を読むことはできない。
- 記事作成（Claudeのスケジュールされたタスク）は、タスクの設定にだけある秘密鍵で復号し、
  事実抽出と検証の担当に渡す。秘密鍵はリポジトリに保存しない。
- 記事が保存されるとキューのファイルは消える。
"""
from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path

from .config import PROJECT_ROOT

CERT = PROJECT_ROOT / "config" / "queue_cert.pem"
DEFAULT_KEY = Path("/tmp/mb_queue_key.pem")


def available_for_encrypt() -> bool:
    return CERT.exists()


def encrypt(text: str) -> str:
    out = subprocess.run(
        ["openssl", "cms", "-encrypt", "-binary", "-aes256", "-outform", "DER", str(CERT)],
        input=text.encode("utf-8"), capture_output=True, check=True,
    ).stdout
    return base64.b64encode(out).decode("ascii")


def key_path() -> Path | None:
    p = Path(os.environ.get("MB_QUEUE_KEY_FILE", DEFAULT_KEY))
    return p if p.exists() else None


def decrypt(blob: str) -> str:
    key = key_path()
    if not key or not blob:
        return ""
    res = subprocess.run(
        ["openssl", "cms", "-decrypt", "-binary", "-inform", "DER", "-inkey", str(key)],
        input=base64.b64decode(blob), capture_output=True,
    )
    return res.stdout.decode("utf-8") if res.returncode == 0 else ""
