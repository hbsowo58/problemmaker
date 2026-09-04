"""조건부 엣지 (CHAP6 rag_agent/edges.py 패턴)

CHAP6의 decide_to_generate / check_hallucinations처럼, 노드가 갱신해 둔 상태를 읽어
다음에 갈 노드 이름만 돌려준다. 상태 변경은 하지 않는다.
"""

from settings import QUESTION_TYPES
from state import QuizState


def decide_after_validate(state: QuizState) -> str:
    """검증 후 라우팅

    - 요청 문항 수를 아직 못 채웠고 재시도 여유가 있으면: 같은 출제 에이전트로 되돌아가 부족분 재출제
    - 목표를 채웠거나 재시도를 소진했으면: 슈퍼바이저로 복귀해 다음 유형 진행
    """

    type_key = state.get("next", "mcq")
    type_label = QUESTION_TYPES[type_key]

    # validate_node가 작업 목록에서 제거했으면 이 유형은 끝난 것
    if type_label not in state.get("plan", []):
        print(f"---DECISION: {type_label} 완료, SUPERVISOR로 복귀---")
        return "supervisor"

    print(f"---DECISION: {type_label} 부족분 재출제 (retry={state.get('retry_num', 0)})---")
    return type_key
