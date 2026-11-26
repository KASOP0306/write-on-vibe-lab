"""루프 A: 질문 퀄리티 상승 루프 (코드 린트 + Fast LLM Critic-Refiner 최대 2회 + ΔSTAR-L 효용 로그)."""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from app.core.bedrock import ainvoke_structured, get_fast_llm
from app.core.vector_store import tokenize_korean_2gram
from app.prompts import build_chat_prompt

logger = logging.getLogger(__name__)

MAX_QUESTION_REVISIONS = 2
PASS_SCORE_THRESHOLD = 80
MAX_QUESTION_LENGTH = 135

_OPEN_INTERROGATIVE_RE = re.compile(
    r"(어떤|어떻게|왜|무엇|얼마나|몇|어느|무슨|어디서|언제|구체적으로|비교|근거|수치|지표|기준|이유|방식|차이|변화)"
)
_CLOSED_ENDING_RE = re.compile(
    r"(있나요|있었나요|했나요|하셨나요|인가요|맞나요|좋아졌나요|되었나요|됐나요|줄었나요|늘었나요|가능한가요)\s*\??$"
)


class QuestionCriticSchema(BaseModel):
    non_redundancy: int = Field(ge=0, le=25)
    answerability: int = Field(ge=0, le=25)
    specificity: int = Field(ge=0, le=25)
    axis_alignment: int = Field(ge=0, le=25)
    total_score: int = Field(ge=0, le=100)
    defects: list[str] = Field(default_factory=list, description="발견된 질문 결함 목록")
    rewrite_instructions: str = Field(
        default="", description="80점 미만일 때 Refiner가 즉시 고칠 핀포인트 지시"
    )


class RefinedQuestionItem(BaseModel):
    technique: str = Field(default="micro_behavioral")
    target_axis: str = Field(default="action")
    question: str = Field(description="개선된 간결하고 날카로운 한국어 개방형 역질문 1문장")
    interviewer_intent: str = Field(default="")
    example_hint: str = Field(default="")


class RefinedQuestionsSchema(BaseModel):
    questions: list[RefinedQuestionItem] = Field(default_factory=list)


def _jaccard_2gram(a: str, b: str) -> float:
    sa = set(tokenize_korean_2gram(a))
    sb = set(tokenize_korean_2gram(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def code_lint_questions(
    questions: list[dict[str, Any]],
    *,
    prev_questions: list[str] | None = None,
    known_text: str = "",
    weakest_axes: list[str] | None = None,
) -> list[str]:
    """비용 0원의 결정론적 질문 품질 린터 (복합 질문·장황함·폐쇄형·중복·약한 축 미적중 탐지)."""
    issues: list[str] = []
    prev_list = [q.strip() for q in (prev_questions or []) if q and q.strip()]
    seen_texts: list[str] = []
    targeted_axes: set[str] = set()

    for idx, item in enumerate(questions, start=1):
        q_text = str(item.get("question") or "").strip()
        axis = str(item.get("target_axis") or "").strip().lower()
        if axis:
            targeted_axes.add(axis)

        if not q_text:
            issues.append(f"질문 #{idx}: 빈 질문")
            continue

        if q_text.count("?") >= 2:
            issues.append(f"질문 #{idx}: 물음표 2개 이상(복합 질문 분리 필요)")

        if len(q_text) > MAX_QUESTION_LENGTH:
            issues.append(f"질문 #{idx}: 길이 초과({len(q_text)}자 > {MAX_QUESTION_LENGTH}자)")

        if _CLOSED_ENDING_RE.search(q_text) and not _OPEN_INTERROGATIVE_RE.search(q_text):
            issues.append(f"질문 #{idx}: 예/아니오 폐쇄형 질문 감지('{q_text[-16:]}')")

        for prev in prev_list:
            if _jaccard_2gram(q_text, prev) >= 0.55:
                issues.append(f"질문 #{idx}: 이전 질문과 중복 유사도 높음")
                break

        for sib in seen_texts:
            if _jaccard_2gram(q_text, sib) >= 0.55:
                issues.append(f"질문 #{idx}: 동일 턴 내 다른 질문과 내용 중복")
                break
        seen_texts.append(q_text)

    if weakest_axes and questions:
        top_weak = weakest_axes[0].lower()
        if top_weak not in targeted_axes:
            issues.append(f"가장 약한 핵심 축('{top_weak}')을 겨냥한 질문이 누락됨")

    return issues


async def critique_and_refine_questions(
    questions: list[dict[str, Any]],
    *,
    context_text: str,
    weakest_axes: list[str] | None = None,
    prev_questions: list[str] | None = None,
    max_revisions: int = MAX_QUESTION_REVISIONS,
    pass_threshold: int = PASS_SCORE_THRESHOLD,
    flow_name: str = "interview",
) -> dict[str, Any]:
    """질문 사전 비평(Critic) → 결함 발견 시 리라이트(Refiner) 폐루프 (최대 2회)."""
    if not questions:
        return {
            "questions": [],
            "critic_score": 0,
            "revisions": 0,
            "lint_issues": [],
            "critic_history": [],
        }

    current = [dict(q) for q in questions]
    critic_history: list[dict[str, Any]] = []
    revisions = 0
    last_score = 100
    last_lint: list[str] = []

    llm = get_fast_llm(temperature=0.15, max_tokens=1600)

    for attempt in range(max_revisions + 1):
        lint_issues = code_lint_questions(
            current,
            prev_questions=prev_questions,
            known_text=context_text,
            weakest_axes=weakest_axes,
        )
        last_lint = lint_issues

        q_preview = "\n".join(
            f"{i}. [axis={q.get('target_axis', '')} | tech={q.get('technique', '')}] {q.get('question', '')}"
            for i, q in enumerate(current, start=1)
        )
        critic_msgs = build_chat_prompt(
            "question_critic",
            (
                "[원문 컨텍스트(이미 알려진 사실)]\n{context_text}\n\n"
                "[가장 약한 STAR-L 축 (우선순위 순)]\n{weakest_axes}\n\n"
                "[이미 물어본 질문 목록]\n{prev_questions}\n\n"
                "[코드 린트 자동 탐지 결함]\n{lint_issues}\n\n"
                "[평가 대상 질문 목록]\n{q_preview}"
            ),
            human_vars={
                "context_text": context_text[:3000],
                "weakest_axes": ", ".join(weakest_axes or []) or "(미지정)",
                "prev_questions": "\n".join(prev_questions or []) or "(없음)",
                "lint_issues": "\n".join(f"- {x}" for x in lint_issues) or "(없음)",
                "q_preview": q_preview,
            },
        )

        try:
            critic_res = await ainvoke_structured(
                llm,
                QuestionCriticSchema,
                critic_msgs,
                max_retries=1,
                caller=f"{flow_name}:question_critic_r{attempt}",
            )
            score = int(
                critic_res.non_redundancy
                + critic_res.answerability
                + critic_res.specificity
                + critic_res.axis_alignment
            )
            # 코드 린트 결함이 남아 있으면 코드 레벨에서 79점 이하로 캡핑
            if lint_issues and score >= pass_threshold:
                score = min(score, pass_threshold - 5)
            defects = list(dict.fromkeys([*lint_issues, *critic_res.defects]))
            instructions = critic_res.rewrite_instructions.strip()
        except Exception as exc:
            logger.warning("Question critic failed (attempt %d): %s", attempt, exc)
            score = 65 if lint_issues else 85
            defects = list(lint_issues)
            instructions = "코드 린트에서 지적된 결함을 수정해 간결한 개방형 1문장으로 고치세요."

        last_score = score
        critic_history.append(
            {
                "attempt": attempt,
                "score": score,
                "lint_issues": lint_issues,
                "defects": defects,
                "rewrite_instructions": instructions,
            }
        )

        if score >= pass_threshold and not lint_issues:
            break
        if attempt >= max_revisions:
            break

        # Refiner 호출 (최대 max_revisions=2회)
        refine_msgs = build_chat_prompt(
            "question_refiner",
            (
                "[원문 컨텍스트(이미 알려진 사실 — 다시 묻지 말 것)]\n{context_text}\n\n"
                "[가장 약한 STAR-L 축]\n{weakest_axes}\n\n"
                "[이전 질문 목록 (반복 금지)]\n{prev_questions}\n\n"
                "[현재 질문 후보 ({count}개)]\n{q_preview}\n\n"
                "[발견된 결함]\n{defects}\n\n"
                "[수정 지시]\n{instructions}"
            ),
            human_vars={
                "context_text": context_text[:3000],
                "weakest_axes": ", ".join(weakest_axes or []) or "(미지정)",
                "prev_questions": "\n".join(prev_questions or []) or "(없음)",
                "count": len(current),
                "q_preview": q_preview,
                "defects": "\n".join(f"- {d}" for d in defects) or "(점수 미달)",
                "instructions": instructions or "결함을 제거하고 가장 약한 축을 파고드는 간결한 개방형 질문으로 개선하세요.",
            },
        )
        try:
            refined = await ainvoke_structured(
                llm,
                RefinedQuestionsSchema,
                refine_msgs,
                max_retries=1,
                caller=f"{flow_name}:question_refiner_r{attempt + 1}",
            )
            if refined.questions:
                next_list: list[dict[str, Any]] = []
                for idx, item in enumerate(refined.questions[: len(current)]):
                    base = current[idx] if idx < len(current) else {}
                    merged = {
                        **base,
                        "technique": item.technique.strip() or base.get("technique", "micro_behavioral"),
                        "target_axis": item.target_axis.strip() or base.get("target_axis", "action"),
                        "question": item.question.strip() or base.get("question", ""),
                        "interviewer_intent": item.interviewer_intent.strip()
                        or base.get("interviewer_intent", ""),
                    }
                    if item.example_hint.strip() or "example_hint" in base:
                        merged["example_hint"] = item.example_hint.strip() or base.get("example_hint", "")
                    if merged["question"]:
                        next_list.append(merged)
                if next_list:
                    current = next_list
                    revisions += 1
        except Exception as exc:
            logger.warning("Question refiner failed (attempt %d): %s", attempt + 1, exc)
            break

    return {
        "questions": current,
        "critic_score": last_score,
        "revisions": revisions,
        "lint_issues": last_lint,
        "critic_history": critic_history,
    }
