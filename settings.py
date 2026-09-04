"""모델과 공통 프롬프트 설정 (CHAP7 settings.py 패턴)"""

import re

from langchain_openai import ChatOpenAI

from dotenv import load_dotenv

load_dotenv()


# 보기 앞에 모델이 붙여 버린 번호를 떼기 위한 패턴
# (①, 1. , 1) , (1) , 가. , A. 형태만 잡는다. "3.14" 같은 값은 건드리지 않도록
# 원문자를 제외하면 뒤에 공백이 오는 경우만 인정한다.
_CHOICE_PREFIX = re.compile(
    r"^\s*(?:[①-⑮]\s*|\(?\d{1,2}[.)]\s+|[가-힣][.)]\s+|[A-Za-z][.)]\s+)"
)


def strip_choice_prefix(text: str) -> str:
    """보기 텍스트 앞의 번호 표기를 제거한다

    화면과 문제지에서 번호를 따로 붙이므로, 모델이 보기 안에 번호를 넣으면
    '① ① 보기내용'처럼 두 번 나온다. 표시 직전에 한 번 걸러 준다.
    """
    text = str(text)

    stripped = text
    for _ in range(3):  # '① ① 보기'처럼 겹쳐 붙은 경우까지 처리
        nxt = _CHOICE_PREFIX.sub("", stripped, count=1).strip()
        if nxt == stripped:
            break
        stripped = nxt

    return stripped or text.strip()


DEFAULT_MODEL = "gpt-4o"
FAST_MODEL = "gpt-4o-mini"

# 생성할 수 있는 문제 유형
QUESTION_TYPES = {
    "mcq": "객관식",
    "short": "주관식",
    "essay": "서술형",
}

# 유형 이름 -> 노드 이름 역방향 매핑
TYPE_BY_LABEL = {label: key for key, label in QUESTION_TYPES.items()}


def get_model(model_name: str = DEFAULT_MODEL, temperature: float = 0.3):
    """공통 모델 팩토리"""
    return ChatOpenAI(model=model_name, temperature=temperature)


def get_supervisor_prompt(current_task: str, plan: list[str], done: dict) -> str:
    """슈퍼바이저 시스템 프롬프트 (CHAP7 supervisor_planning_agent 패턴)"""
    done_summary = ", ".join(
        f"{label} {count}문항" for label, count in done.items() if count
    ) or "아직 없음"

    return f"""
    당신은 PDF 문서 기반 문제 출제 시스템의 슈퍼바이저입니다.
    Router 도구를 사용하여 현재 작업을 수행할 출제 에이전트를 결정하세요.

    ## 현재 작업 (이것만 처리하세요)
    {current_task}

    ## 남은 작업 목록
    {plan}

    ## 이미 완료한 출제
    {done_summary}

    ## 팀 멤버
    - mcq: 객관식(4지선다) 문항 출제 담당
    - short: 주관식(단답/서술 1~2문장) 문항 출제 담당
    - essay: 서술형(논술) 문항 출제 담당

    현재 작업 "{current_task}"에 해당하는 에이전트 **하나만** 호출하세요.
    """


def get_generator_prompt(type_label: str, difficulty: str, count: int) -> str:
    """출제 에이전트 공통 시스템 프롬프트"""

    rules = {
        "객관식": """
        - 보기는 정확히 4개(choices 4개)를 만드세요.
        - **보기 텍스트에 번호를 넣지 마세요.** ①②③④, 1., (1), 가. 같은 표기를 붙이면 안 됩니다.
          번호는 화면에서 자동으로 붙습니다. 보기 내용만 쓰세요.
        - 정답은 answer_index(0~3)로 표기하세요.
        - 오답 보기도 그럴듯해야 하며, '모두 정답', '정답 없음' 같은 보기는 만들지 마세요.
        - 보기 길이를 비슷하게 맞추어 정답이 티나지 않게 하세요.
        """,
        "주관식": """
        - 한 단어 ~ 두 문장 이내로 답할 수 있는 문항을 만드세요.
        - answer에는 모범 답안을, keywords에는 채점 시 확인할 핵심어를 3개 내외로 넣으세요.
        - 답이 여러 표현으로 가능한 경우 keywords로 그 범위를 표현하세요.
        """,
        "서술형": """
        - 단순 암기가 아니라 비교/분석/적용/설명을 요구하는 문항을 만드세요.
        - answer에는 모범 답안을 5문장 내외로 작성하세요.
        - rubric에는 채점 기준을 3개 항목으로 나누어 작성하세요.
        """,
    }

    return f"""
    당신은 주어진 문서 발췌문만을 근거로 시험 문제를 출제하는 출제 전문가입니다.

    ## 출제 유형: {type_label}
    ## 난이도: {difficulty}
    ## 출제 문항 수: {count}개

    ## 절대 규칙
    1. **반드시 제공된 '문서 발췌문' 안의 내용만으로** 문항과 정답을 만드세요.
       발췌문에 없는 사실을 추가하거나 일반 상식으로 보충하지 마세요.
    2. 각 문항의 source_quote에는 근거가 된 발췌문 원문을 **그대로** 1~2문장 인용하세요.
    3. 각 문항의 page에는 근거 문장이 있는 페이지 번호를 적으세요.
    4. 이미 출제된 문항과 내용이 겹치지 않게 하세요.
    5. 모든 문항은 한국어로 작성하세요.

    ## 유형별 규칙
    {rules.get(type_label, "")}
    """


def get_grader_prompt() -> str:
    """근거 검증(환각 검사) 프롬프트 (CHAP6 rag_agent/edges.py 패턴)"""
    return """
    당신은 출제된 문항이 원문 발췌에 근거하고 있는지 평가하는 평가자입니다.

    다음을 모두 만족하면 'yes', 하나라도 어기면 'no'로 평가하세요.
    1. 문항이 묻는 내용이 발췌문 안에 실제로 존재하는가
    2. 제시된 정답이 발췌문에 비추어 옳은가
    3. source_quote가 발췌문에 실제로 등장하는 표현인가

    엄격한 테스트일 필요는 없습니다. 목표는 문서에 없는 내용을 지어낸 문항을 걸러내는 것입니다.
    'yes' 또는 'no'의 이진 점수와, 'no'인 경우 짧은 사유를 함께 제공하세요.
    """
