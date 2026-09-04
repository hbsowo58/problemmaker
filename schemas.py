"""구조화 출력 스키마 (CHAP6 edges.py / CHAP7 planning_agent.py 패턴)"""

from typing import List, Literal

from pydantic import BaseModel, Field


# ===== 출제 계획 =====

class QuizPlan(BaseModel):
    """문서를 분석해 세운 출제 계획"""

    doc_summary: str = Field(description="문서 전체 내용을 3~4문장으로 요약")
    topics: List[str] = Field(
        description="출제할 만한 핵심 주제 3~6개. 각 주제는 검색 쿼리로 쓸 수 있게 구체적으로"
    )


# ===== 문항 스키마 =====

class MCQ(BaseModel):
    """객관식 문항"""

    question: str = Field(description="문제 본문")
    choices: List[str] = Field(description="보기 4개", min_length=4, max_length=4)
    answer_index: int = Field(description="정답 보기의 인덱스 (0~3)", ge=0, le=3)
    explanation: str = Field(description="정답 해설")
    source_quote: str = Field(description="근거가 된 발췌문 원문 1~2문장")
    page: int = Field(description="근거 문장이 있는 페이지 번호")


class ShortAnswer(BaseModel):
    """주관식 문항"""

    question: str = Field(description="문제 본문")
    answer: str = Field(description="모범 답안 (한 단어 ~ 두 문장)")
    keywords: List[str] = Field(description="채점 시 확인할 핵심어 3개 내외")
    explanation: str = Field(description="정답 해설")
    source_quote: str = Field(description="근거가 된 발췌문 원문 1~2문장")
    page: int = Field(description="근거 문장이 있는 페이지 번호")


class Essay(BaseModel):
    """서술형 문항"""

    question: str = Field(description="문제 본문")
    answer: str = Field(description="모범 답안 5문장 내외")
    rubric: List[str] = Field(description="채점 기준 3개 항목")
    source_quote: str = Field(description="근거가 된 발췌문 원문 1~2문장")
    page: int = Field(description="근거 문장이 있는 페이지 번호")


# ===== 배치 출력용 래퍼 =====

class MCQList(BaseModel):
    items: List[MCQ]


class ShortAnswerList(BaseModel):
    items: List[ShortAnswer]


class EssayList(BaseModel):
    items: List[Essay]


SCHEMA_BY_TYPE = {
    "mcq": MCQList,
    "short": ShortAnswerList,
    "essay": EssayList,
}


# ===== 검증 스키마 =====

class Grade(BaseModel):
    """문항이 발췌문에 근거하는지 판단하는 이진 점수"""

    binary_score: Literal["yes", "no"] = Field(
        description="문항이 발췌문에 근거하고 정답이 옳으면 'yes', 아니면 'no'"
    )
    reason: str = Field(description="'no'인 경우의 사유. 'yes'면 빈 문자열")
