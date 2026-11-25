"""외부 텍스트 프롬프트 로더 및 LangChain ChatPromptTemplate 빌더 (Unit 2)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate

PROMPTS_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=64)
def load_prompt(name: str) -> str:
    """`backend/app/prompts/{name}.txt` 파일을 UTF-8로 읽어 캐시 반환한다."""
    filename = name if name.endswith(".txt") else f"{name}.txt"
    path = PROMPTS_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def render_prompt(name: str, **variables: Any) -> str:
    """외부 프롬프트 파일에 변수를 주입해 렌더링한다.

    변수 치환이 필요 없으면 원문을 그대로 반환한다.
    """
    template_text = load_prompt(name)
    if not variables:
        return template_text
    return template_text.format(**variables)


def build_chat_prompt(
    system_prompt_name: str,
    human_template: str,
    *,
    system_vars: dict[str, Any] | None = None,
    human_vars: dict[str, Any] | None = None,
) -> list[BaseMessage]:
    """외부 시스템 프롬프트 파일 + 휴먼 템플릿을 ChatPromptTemplate으로 메시지 목록 생성."""
    system_text = render_prompt(system_prompt_name, **(system_vars or {}))
    # 시스템 텍스트 내부의 중괄호(JSON 예시 등)가 ChatPromptTemplate 변수로 오해되지 않게 이스케이프
    safe_system = system_text.replace("{", "{{").replace("}", "}}")
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", safe_system),
            ("human", human_template),
        ]
    )
    return prompt.format_messages(**(human_vars or {}))
