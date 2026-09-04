"""그래프 조립 (CHAP7 make_graph.py + CHAP8 체크포인터 패턴)

    START → planning → supervisor ─┬→ mcq   ─┐
                                   ├→ short ─┼→ validate ─┬→ (부족하면 같은 에이전트로)
                                   └→ essay ─┘            └→ supervisor → … → END
"""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from edges import decide_after_validate
from nodes import (
    essay_node,
    mcq_node,
    planning_node,
    short_node,
    supervisor_node,
    validate_node,
)
from state import QuizState


def build_graph(checkpointer=None):
    """그래프를 컴파일해 반환

    checkpointer를 넘기면 thread_id 단위로 대화/출제 상태가 유지된다 (CHAP8).
    """

    graph_builder = StateGraph(QuizState)  # [1] 상태 스키마

    # [2] 노드 등록. Command로 이동하는 노드는 destinations로 목적지를 선언한다.
    graph_builder.add_node("planning", planning_node, destinations=("supervisor", END))
    graph_builder.add_node(
        "supervisor", supervisor_node, destinations=("mcq", "short", "essay", END)
    )
    graph_builder.add_node("mcq", mcq_node, destinations=("validate",))
    graph_builder.add_node("short", short_node, destinations=("validate",))
    graph_builder.add_node("essay", essay_node, destinations=("validate",))
    graph_builder.add_node("validate", validate_node)

    graph_builder.add_edge(START, "planning")

    # [3] 검증 후 라우팅만 조건부 엣지로 처리 (CHAP6 스타일)
    graph_builder.add_conditional_edges(
        "validate",
        decide_after_validate,
        {
            "mcq": "mcq",
            "short": "short",
            "essay": "essay",
            "supervisor": "supervisor",
        },
    )

    return graph_builder.compile(checkpointer=checkpointer)


# langgraph dev / langgraph.json 용 기본 그래프
graph = build_graph(checkpointer=InMemorySaver())


if __name__ == "__main__":
    from pathlib import Path

    try:
        png = graph.get_graph().draw_mermaid_png()
        path = Path(__file__).parent / "graph.png"
        path.write_bytes(png)
        print(f"그래프 이미지를 저장했습니다: {path}")
    except Exception as error:
        print(f"이미지 렌더링 실패(무시 가능): {error}")

    print(graph.get_graph().draw_mermaid())
