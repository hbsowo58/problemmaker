"""그래프 상태 정의 (CHAP6 rag_agent/state.py, CHAP7 settings.py 패턴)"""

from typing import Dict, List

from langgraph.graph import MessagesState


class QuizState(MessagesState):
    """PDF 문제 출제 그래프의 상태

    MessagesState를 상속하므로 messages 필드(add_messages 리듀서)를 그대로 사용한다.
    """

    # --- 입력 ---
    doc_id: str            # 업로드한 PDF의 식별자 (retriever 조회 키)
    doc_name: str          # 원본 파일명
    difficulty: str        # 난이도: 하 / 중 / 상
    counts: Dict[str, int]  # 유형별 요청 문항 수 {"mcq": 5, "short": 3, "essay": 2}

    # --- planning 결과 ---
    doc_summary: str
    topics: List[str]
    plan: List[str]        # 남은 작업 라벨 ["객관식", "주관식", "서술형"]

    # --- 라우팅 ---
    next: str              # 슈퍼바이저가 선택한 에이전트 키 (mcq / short / essay)

    # --- 출제 결과 (누적) ---
    mcqs: List[dict]
    shorts: List[dict]
    essays: List[dict]

    # --- 검증 ---
    last_batch: List[dict]  # 방금 생성해 아직 검증되지 않은 문항
    last_context: str       # 그 문항을 만들 때 사용한 발췌문
    rejected: List[str]     # 검증에서 탈락한 사유 로그
    retry_num: int          # 현재 유형의 재시도 횟수
