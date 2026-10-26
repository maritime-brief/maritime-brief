"""Claude API の呼び出し口。

各エージェントは call_json() で「JSONだけを返す」よう指示して呼び出す。
APIキーなしで動作確認できるよう、デモ用の MockLLM も用意している。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Callable

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


def parse_json(text: str) -> dict:
    """応答からJSONを取り出す。```json ... ``` で囲まれていても読める。"""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise LLMError("JSONが見つかりませんでした")
        text = text[start : end + 1]
    return json.loads(text)


class ClaudeLLM:
    def __init__(self):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise LLMError(
                "ANTHROPIC_API_KEY が設定されていません。GitHub の Settings → Secrets に登録してください。"
                "（APIを使わずに動作確認するには --demo を付けて実行します）"
            )
        import anthropic

        self.client = anthropic.Anthropic(api_key=api_key)
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

    def call_json(self, agent: str, model: str, system: str, user: str, max_tokens: int = 2000) -> dict:
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                resp = self.client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                self.usage["calls"] += 1
                self.usage["input_tokens"] += resp.usage.input_tokens
                self.usage["output_tokens"] += resp.usage.output_tokens
                text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
                return parse_json(text)
            except (json.JSONDecodeError, LLMError) as e:
                last_err = e
                log.warning("[%s] JSONの読み取りに失敗（%d回目）: %s", agent, attempt + 1, e)
            except Exception as e:  # ネットワークや混雑による一時的な失敗
                last_err = e
                log.warning("[%s] API呼び出しに失敗（%d回目）: %s", agent, attempt + 1, e)
                time.sleep(5 * (attempt + 1))
        raise LLMError(f"[{agent}] 3回試しても結果を得られませんでした: {last_err}")


class MockLLM:
    """APIを使わないデモ用。エージェント名ごとに決まった応答を返す。"""

    def __init__(self, handlers: dict[str, Callable[[str], dict]]):
        self.handlers = handlers
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

    def call_json(self, agent: str, model: str, system: str, user: str, max_tokens: int = 2000) -> dict:
        self.usage["calls"] += 1
        return self.handlers[agent](user)
