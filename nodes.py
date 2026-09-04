"""그래프 노드 정의

- planning_node   : 문서 분석 후 출제 계획 수립 (CHAP7 planning_agent.py 패턴)
- supervisor_node : Router 도구로 출제 에이전트 선택 (CHAP7 supervisor_agent.py 패턴)
- mcq/short/essay : 검색 -> 구조화 출력으로 문항 생성 (CHAP6 rag_agent/nodes.py 패턴)
- validate_node   : 생성된 문항의 근거 검증 (CHAP6 check_hallucinations 패턴)
"""

from typing import Literal, TypedDict

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END
from langgraph.types import Command

from retriever import get_outline, retrieve_context
from schemas import SCHEMA_BY_TYPE, Grade, QuizPlan
from settings import (
    FAST_MODEL,
    QUESTION_TYPES,
    TYPE_BY_LABEL,
    get_generator_prompt,
    get_grader_prompt,
    get_model,
    get_supervisor_prompt,
)
from state import QuizState

MAX_RETRY = 2

# 유형 키 -> 상태에 누적할 필드명
RESULT_FIELD = {"mcq": "mcqs", "short": "shorts", "essay": "essays"}


class Router(TypedDict):
    """작업을 수행할 출제 에이전트를 라우팅합니다."""

    next: Literal["mcq", "short", "essay"]


# =====================================================================
# 1) Planning
# =====================================================================

def planning_node(state: QuizState) -> Command:
    """문서를 훑어 요약과 출제 주제를 뽑고, 유형별 작업 목록을 만든다"""

    doc_id = state["doc_id"]
    counts = state.get("counts", {})

    outline = get_outline(doc_id)

    planner_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """당신은 학습 자료를 분석해 출제 계획을 세우는 전문가입니다.
                주어진 문서 발췌를 읽고 전체 요약과, 문제로 낼 만한 핵심 주제를 뽑으세요.

                주제 선정 기준:
                - 문서에 실제로 설명이 충분히 담긴 내용만 고르세요.
                - 각 주제는 벡터 검색 쿼리로 바로 쓸 수 있게 구체적인 명사구로 작성하세요.
                - 서로 내용이 겹치지 않게 3~6개를 고르세요.""",
            ),
            ("user", "문서 발췌:\n{outline}"),
        ]
    )

    planner = planner_prompt | get_model().with_structured_output(QuizPlan)
    result = planner.invoke({"outline": outline})

    # 요청 수가 1개 이상인 유형만 작업 목록에 넣는다
    plan = [
        QUESTION_TYPES[key]
        for key in ("mcq", "short", "essay")
        if counts.get(key, 0) > 0
    ]

    message = AIMessage(
        content=(
            f"문서 분석을 마쳤습니다.\n\n"
            f"**요약**: {result.doc_summary}\n\n"
            f"**출제 주제**: {', '.join(result.topics)}\n\n"
            f"**작업 계획**: {' → '.join(plan) if plan else '없음'}"
        ),
        name="planning",
    )

    return Command(
        goto="supervisor" if plan else END,
        update={
            "doc_summary": result.doc_summary,
            "topics": result.topics,
            "plan": plan,
            "messages": [message],
        },
    )


# =====================================================================
# 2) Supervisor
# =====================================================================

def supervisor_node(state: QuizState) -> Command[Literal["mcq", "short", "essay", END]]:
    """남은 작업이 있으면 담당 에이전트로 라우팅, 없으면 최종 정리 후 종료"""

    plan = state.get("plan", [])

    # [1] 남은 작업이 없으면 종료
    if not plan:
        done = {
            "객관식": len(state.get("mcqs", [])),
            "주관식": len(state.get("shorts", [])),
            "서술형": len(state.get("essays", [])),
        }
        summary = ", ".join(f"{label} {n}문항" for label, n in done.items() if n)
        rejected = state.get("rejected", [])

        content = f"출제를 마쳤습니다. 총 {sum(done.values())}문항 ({summary})."
        if rejected:
            content += f"\n\n검증에서 제외된 문항 {len(rejected)}건이 있습니다."

        return Command(
            goto=END,
            update={"messages": [AIMessage(content=content, name="supervisor")]},
        )

    # [2] Router 도구로 담당 에이전트 결정
    current_task = plan[0]
    done_counts = {
        "객관식": len(state.get("mcqs", [])),
        "주관식": len(state.get("shorts", [])),
        "서술형": len(state.get("essays", [])),
    }

    llm = get_model(temperature=0)
    response = llm.bind_tools([Router]).invoke(
        [{"role": "system", "content": get_supervisor_prompt(current_task, plan, done_counts)}]
    )

    if getattr(response, "tool_calls", None):
        goto = response.tool_calls[0]["args"]["next"]
    else:
        # [3] 도구를 호출하지 않은 경우엔 계획을 그대로 따른다 (안전장치)
        goto = TYPE_BY_LABEL[current_task]

    return Command(
        goto=goto,
        update={
            "next": goto,
            "retry_num": 0,
            "messages": [
                AIMessage(content=f"'{current_task}' 출제를 시작합니다.", name="supervisor")
            ],
        },
    )


# =====================================================================
# 3) 출제 에이전트 (세 유형이 같은 로직을 공유)
# =====================================================================

def _generate(state: QuizState, type_key: str) -> Command:
    doc_id = state["doc_id"]
    type_label = QUESTION_TYPES[type_key]
    difficulty = state.get("difficulty", "중")
    topics = state.get("topics", []) or [state.get("doc_summary", "")]

    # [1] 이미 확보한 문항을 빼고 부족한 만큼만 생성한다
    #     (검증 탈락 후 재시도, 그리고 CHAP8 메모리로 '이어서 더 만들기' 할 때 모두 이 계산을 탄다)
    existing = state.get(RESULT_FIELD[type_key], [])
    count = max(state.get("counts", {}).get(type_key, 0) - len(existing), 0)

    # [2] 주제별로 검색해 근거 발췌문을 모은다
    context = retrieve_context(doc_id, topics, k=4)

    # [3] 이미 만든 문항은 중복 방지를 위해 프롬프트에 알려준다
    already = "\n".join(f"- {q['question']}" for q in existing)
    already_block = f"\n\n## 이미 출제된 문항 (중복 금지)\n{already}" if already else ""

    retry_note = ""
    if state.get("retry_num", 0):
        rejected = state.get("rejected", [])[-3:]
        retry_note = (
            "\n\n## 직전 시도에서 탈락한 사유 (반복하지 마세요)\n"
            + "\n".join(f"- {r}" for r in rejected)
        )

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", get_generator_prompt(type_label, difficulty, count) + already_block + retry_note),
            ("user", "문서 발췌문:\n{context}\n\n위 발췌문만 근거로 {count}개의 {type_label} 문항을 출제하세요."),
        ]
    )

    schema = SCHEMA_BY_TYPE[type_key]
    generator = prompt | get_model(temperature=0.4).with_structured_output(schema)
    result = generator.invoke(
        {"context": context, "count": count, "type_label": type_label}
    )

    batch = [item.model_dump() for item in result.items]

    message = AIMessage(
        content=f"{type_label} {len(batch)}문항 초안을 작성했습니다. 근거 검증으로 넘깁니다.",
        name=f"{type_key}_agent",
    )

    return Command(
        goto="validate",
        update={
            "last_batch": batch,
            "last_context": context,
            "next": type_key,
            "messages": [message],
        },
    )


def mcq_node(state: QuizState) -> Command[Literal["validate"]]:
    """객관식 출제 에이전트"""
    return _generate(state, "mcq")


def short_node(state: QuizState) -> Command[Literal["validate"]]:
    """주관식 출제 에이전트"""
    return _generate(state, "short")


def essay_node(state: QuizState) -> Command[Literal["validate"]]:
    """서술형 출제 에이전트"""
    return _generate(state, "essay")


# =====================================================================
# 4) 검증
# =====================================================================

def validate_node(state: QuizState) -> dict:
    """생성된 문항이 발췌문에 근거하는지 문항별로 채점한다

    라우팅은 edges.decide_after_validate가 담당한다 (CHAP6 rag_agent 패턴).
    """

    batch = state.get("last_batch", [])
    context = state.get("last_context", "")
    type_key = state.get("next", "mcq")
    type_label = QUESTION_TYPES[type_key]

    grader = get_model(FAST_MODEL, temperature=0).with_structured_output(Grade)
    grader_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", get_grader_prompt()),
            (
                "user",
                "발췌문:\n{context}\n\n"
                "문항: {question}\n"
                "정답/모범답안: {answer}\n"
                "인용한 근거: {quote}\n\n"
                "평가:",
            ),
        ]
    )
    chain = grader_prompt | grader

    passed, rejected = [], []
    for item in batch:
        answer = item.get("answer")
        if answer is None and "answer_index" in item:  # 객관식
            answer = item["choices"][item["answer_index"]]

        score = chain.invoke(
            {
                "context": context,
                "question": item["question"],
                "answer": answer,
                "quote": item.get("source_quote", ""),
            }
        )

        if score.binary_score == "yes":
            passed.append(item)
        else:
            rejected.append(f"[{type_label}] {item['question'][:40]}… → {score.reason}")

    # 통과한 문항만 누적
    field = RESULT_FIELD[type_key]
    merged = list(state.get(field, [])) + passed

    # [1] 목표 수를 채웠거나 재시도를 소진했으면 이 유형을 작업 목록에서 제거한다.
    #     라우팅 판단(edges.decide_after_validate)은 아래 plan/retry_num만 보고 이뤄진다.
    requested = state.get("counts", {}).get(type_key, 0)
    retry_num = state.get("retry_num", 0)
    finished = len(merged) >= requested or retry_num >= MAX_RETRY

    plan = list(state.get("plan", []))
    if finished and type_label in plan:
        plan.remove(type_label)

    detail = f"{type_label} 검증 결과: 통과 {len(passed)}건 / 탈락 {len(rejected)}건"
    if not finished:
        detail += f" → 부족분 재출제 ({len(merged)}/{requested})"

    return {
        field: merged,
        "plan": plan,
        "retry_num": 0 if finished else retry_num + 1,
        "last_batch": passed,
        "rejected": list(state.get("rejected", [])) + rejected,
        "messages": [AIMessage(content=detail, name="validator")],
    }
