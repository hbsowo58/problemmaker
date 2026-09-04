"""사용자가 푼 답안을 채점한다

- 객관식: 보기 인덱스 비교 (LLM 호출 없음)
- 주관식/서술형: LLM이 모범답안·핵심어·채점기준에 비추어 판정
  (CHAP6 rag_agent/edges.py의 구조화 출력 평가자 패턴)
"""

from typing import List, Literal, Optional

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from settings import DEFAULT_MODEL, FAST_MODEL, get_model, strip_choice_prefix


# =====================================================================
# 채점 결과 스키마
# =====================================================================

class ShortGrade(BaseModel):
    """주관식 채점 결과"""

    verdict: Literal["정답", "부분정답", "오답"] = Field(description="판정")
    score: int = Field(description="0~100점", ge=0, le=100)
    feedback: str = Field(description="왜 그렇게 판정했는지 1~2문장. 학습자에게 말하듯이")
    missed_keywords: List[str] = Field(description="답안에서 빠진 핵심어. 없으면 빈 목록")


class RubricCheck(BaseModel):
    criterion: str = Field(description="채점 기준 항목")
    met: bool = Field(description="충족 여부")
    comment: str = Field(description="한 문장 코멘트")


class EssayGrade(BaseModel):
    """서술형 채점 결과"""

    score: int = Field(description="0~100점", ge=0, le=100)
    rubric_checks: List[RubricCheck] = Field(description="채점 기준 항목별 평가")
    strengths: str = Field(description="잘한 점 1~2문장")
    improvements: str = Field(description="보완할 점 1~2문장")


# =====================================================================
# 채점 로직
# =====================================================================

SHORT_SYSTEM = """
당신은 서술형 답안을 관대하지만 정확하게 채점하는 채점자입니다.

채점 원칙:
1. **표현이 달라도 의미가 같으면 정답입니다.** 모범답안과 글자가 일치할 필요는 없습니다.
2. 핵심 개념을 맞혔으나 일부가 빠졌다면 '부분정답'으로 처리하세요.
3. 핵심 개념이 틀렸거나 관계없는 답이면 '오답'입니다.
4. 맞춤법이나 띄어쓰기는 감점 사유가 아닙니다.
5. 피드백은 채점자 말투가 아니라 학습자에게 설명하듯 친절하게 쓰세요.
"""

ESSAY_SYSTEM = """
당신은 논술형 답안을 채점 기준(루브릭)에 따라 평가하는 채점자입니다.

채점 원칙:
1. 채점 기준 **각 항목별로** 충족 여부를 판단하세요.
2. 모범답안과 구성이나 순서가 달라도, 요구된 내용을 담고 있으면 충족으로 봅니다.
3. 분량이 짧아도 핵심을 짚었다면 충족으로 인정하세요. 길다고 가점하지 마세요.
4. 점수는 충족한 기준의 비율을 기본으로 하되, 설명의 정확성과 깊이를 반영해 조정하세요.
5. 답안이 비었거나 문항과 무관하면 0점입니다.
6. 잘한 점과 보완할 점을 모두 구체적으로 짚어 주세요.
"""


def grade_mcq(question: dict, selected_index: Optional[int]) -> dict:
    """객관식 채점 - 인덱스 비교라 LLM이 필요 없다"""

    if selected_index is None:
        return {
            "type": "mcq",
            "question": question["question"],
            "user_answer": None,
            "correct_answer": strip_choice_prefix(question["choices"][question["answer_index"]]),
            "verdict": "미응답",
            "score": 0,
            "feedback": "답을 선택하지 않았습니다.",
            "explanation": question["explanation"],
            "page": question["page"],
        }

    is_correct = selected_index == question["answer_index"]

    return {
        "type": "mcq",
        "question": question["question"],
        "user_answer": strip_choice_prefix(question["choices"][selected_index]),
        "correct_answer": strip_choice_prefix(question["choices"][question["answer_index"]]),
        "verdict": "정답" if is_correct else "오답",
        "score": 100 if is_correct else 0,
        "feedback": question["explanation"],
        "explanation": question["explanation"],
        "page": question["page"],
    }


def grade_short(question: dict, user_answer: str) -> dict:
    """주관식 채점"""

    user_answer = (user_answer or "").strip()
    if not user_answer:
        return _blank(question, "short", question["answer"])

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SHORT_SYSTEM),
            (
                "user",
                "문항: {question}\n\n"
                "모범답안: {answer}\n"
                "채점 핵심어: {keywords}\n"
                "문서 근거: {quote}\n\n"
                "학습자 답안: {user_answer}\n\n"
                "채점:",
            ),
        ]
    )

    grader = prompt | get_model(FAST_MODEL, temperature=0).with_structured_output(ShortGrade)
    result = grader.invoke(
        {
            "question": question["question"],
            "answer": question["answer"],
            "keywords": ", ".join(question.get("keywords", [])),
            "quote": question.get("source_quote", ""),
            "user_answer": user_answer,
        }
    )

    return {
        "type": "short",
        "question": question["question"],
        "user_answer": user_answer,
        "correct_answer": question["answer"],
        "verdict": result.verdict,
        "score": result.score,
        "feedback": result.feedback,
        "missed_keywords": result.missed_keywords,
        "explanation": question.get("explanation", ""),
        "page": question["page"],
    }


def grade_essay(question: dict, user_answer: str) -> dict:
    """서술형 채점"""

    user_answer = (user_answer or "").strip()
    if not user_answer:
        return _blank(question, "essay", question["answer"])

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", ESSAY_SYSTEM),
            (
                "user",
                "문항: {question}\n\n"
                "모범답안: {answer}\n\n"
                "채점 기준:\n{rubric}\n\n"
                "문서 근거: {quote}\n\n"
                "학습자 답안: {user_answer}\n\n"
                "채점:",
            ),
        ]
    )

    grader = prompt | get_model(DEFAULT_MODEL, temperature=0).with_structured_output(EssayGrade)
    result = grader.invoke(
        {
            "question": question["question"],
            "answer": question["answer"],
            "rubric": "\n".join(f"- {r}" for r in question.get("rubric", [])),
            "quote": question.get("source_quote", ""),
            "user_answer": user_answer,
        }
    )

    met = sum(1 for check in result.rubric_checks if check.met)
    total = len(result.rubric_checks) or 1

    return {
        "type": "essay",
        "question": question["question"],
        "user_answer": user_answer,
        "correct_answer": question["answer"],
        "verdict": f"기준 {met}/{total} 충족",
        "score": result.score,
        "feedback": f"**잘한 점** {result.strengths}\n\n**보완할 점** {result.improvements}",
        "rubric_checks": [check.model_dump() for check in result.rubric_checks],
        "page": question["page"],
    }


def _blank(question: dict, type_key: str, correct: str) -> dict:
    return {
        "type": type_key,
        "question": question["question"],
        "user_answer": "",
        "correct_answer": correct,
        "verdict": "미응답",
        "score": 0,
        "feedback": "답안을 작성하지 않았습니다.",
        "page": question["page"],
    }


def grade_all(state: dict, answers: dict, on_progress=None) -> dict:
    """전체 답안을 채점하고 요약과 함께 돌려준다

    answers 형식: {"mcq_0": 2, "short_1": "구개음화", "essay_0": "..."}
    """

    graded: List[dict] = []
    pairs = (
        [("mcq", q) for q in state.get("mcqs", [])]
        + [("short", q) for q in state.get("shorts", [])]
        + [("essay", q) for q in state.get("essays", [])]
    )

    counters = {"mcq": 0, "short": 0, "essay": 0}
    for type_key, question in pairs:
        i = counters[type_key]
        counters[type_key] += 1
        key = f"{type_key}_{i}"

        if on_progress:
            on_progress(len(graded) + 1, len(pairs))

        if type_key == "mcq":
            graded.append(grade_mcq(question, answers.get(key)))
        elif type_key == "short":
            graded.append(grade_short(question, answers.get(key, "")))
        else:
            graded.append(grade_essay(question, answers.get(key, "")))

    # 유형별 / 전체 요약
    def average(items):
        return round(sum(g["score"] for g in items) / len(items)) if items else None

    by_type = {t: [g for g in graded if g["type"] == t] for t in ("mcq", "short", "essay")}

    return {
        "items": graded,
        "total_score": average(graded) or 0,
        "count": len(graded),
        "correct_count": sum(1 for g in graded if g["score"] >= 80),
        "by_type": {t: average(items) for t, items in by_type.items() if items},
    }
