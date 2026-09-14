"""PDF 문제 출제 사이트 (PART2 app.py의 Streamlit 구조 + CHAP6~8 에이전트)"""

import hmac
import os
import uuid

import streamlit as st
from dotenv import load_dotenv
from langgraph.checkpoint.memory import InMemorySaver

import retriever as retriever_module
from export import to_json, to_markdown
from grading import grade_all
from make_graph import build_graph
from settings import QUESTION_TYPES, strip_choice_prefix

load_dotenv()

st.set_page_config(page_title="PDF 문제 출제기", page_icon="📝", layout="wide")

CIRCLED = ["①", "②", "③", "④"]

NODE_LABEL = {
    "planning": "📋 문서 분석 및 출제 계획 수립",
    "supervisor": "🧭 담당 에이전트 배정",
    "mcq": "🅰️ 객관식 출제",
    "short": "✏️ 주관식 출제",
    "essay": "📄 서술형 출제",
    "validate": "🔍 근거 검증",
}


# =====================================================================
# 비밀번호 게이트
# =====================================================================

def read_secret(name: str) -> str | None:
    """Streamlit Secrets를 먼저 보고, 없으면 환경변수(.env)를 본다"""
    try:
        return st.secrets[name]
    except Exception:
        return os.getenv(name)


def check_password() -> bool:
    """APP_PASSWORD가 설정된 경우에만 비밀번호를 요구한다

    로컬에서 .env에 APP_PASSWORD를 넣지 않으면 게이트 없이 바로 들어간다.
    배포 시에는 Streamlit Secrets에 APP_PASSWORD를 넣어 잠근다.
    """

    expected = read_secret("APP_PASSWORD")

    if not expected:              # 비밀번호 미설정 = 게이트 비활성
        return True
    if st.session_state.get("authenticated"):
        return True

    st.title("📝 PDF 문제 출제기")
    st.caption("이용하려면 비밀번호가 필요합니다.")

    with st.form("login"):
        password = st.text_input("비밀번호", type="password")
        submitted = st.form_submit_button("입장")

    if submitted:
        # 문자열 비교 시간으로 정답을 추측하지 못하도록 상수 시간 비교를 쓴다
        if hmac.compare_digest(password, str(expected)):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("비밀번호가 틀렸습니다.")

    return False


if not check_password():
    st.stop()


# =====================================================================
# API 키 확인
# =====================================================================

def resolve_api_key() -> str | None:
    return read_secret("OPENAI_API_KEY")


api_key = resolve_api_key()
if api_key:
    os.environ["OPENAI_API_KEY"] = api_key


# =====================================================================
# 세션 상태 (CHAP8: thread_id 하나가 하나의 출제 세션)
# =====================================================================

if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
if "checkpointer" not in st.session_state:
    st.session_state.checkpointer = InMemorySaver()
if "graph" not in st.session_state:
    st.session_state.graph = build_graph(checkpointer=st.session_state.checkpointer)
if "result" not in st.session_state:
    st.session_state.result = None
if "doc_id" not in st.session_state:
    st.session_state.doc_id = None
if "report" not in st.session_state:
    st.session_state.report = None


# =====================================================================
# 사이드바 - 출제 옵션
# =====================================================================

with st.sidebar:
    st.header("⚙️ 출제 설정")

    if not api_key:
        st.error("OPENAI_API_KEY가 없습니다. `.env`에 넣어주세요.")
    else:
        st.success("OPENAI_API_KEY 확인됨")

    st.divider()

    mcq_count = st.slider("객관식 문항 수", 0, 10, 5)
    short_count = st.slider("주관식 문항 수", 0, 10, 3)
    essay_count = st.slider("서술형 문항 수", 0, 5, 2)

    difficulty = st.select_slider("난이도", options=["하", "중", "상"], value="중")

    st.divider()

    if st.button("🗑️ 세션 초기화", use_container_width=True):
        thread_id = st.session_state.thread_id
        st.session_state.checkpointer.delete_thread(thread_id)  # CHAP8: 스레드 삭제
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.result = None
        st.session_state.report = None
        st.rerun()

    if st.session_state.get("authenticated"):
        if st.button("🔒 로그아웃", use_container_width=True):
            st.session_state.authenticated = False
            st.rerun()

    st.caption(f"thread_id: `{st.session_state.thread_id[:8]}…`")


# =====================================================================
# 본문 - PDF 업로드
# =====================================================================

st.title("📝 PDF 문제 출제기")
st.caption("PDF를 올리면 객관식·주관식·서술형 문제를 문서 근거와 함께 만들어 드립니다.")

uploaded = st.file_uploader("PDF 파일을 올려주세요", type=["pdf"])

if uploaded is not None:
    pdf_bytes = uploaded.getvalue()
    doc_id = retriever_module.make_doc_id(pdf_bytes)

    if not retriever_module.has_index(doc_id):
        if not api_key:
            st.stop()

        status = st.status("PDF를 읽고 색인하는 중…", expanded=False)

        def on_ocr_progress(done: int, total: int) -> None:
            """텍스트 레이어가 없는 페이지를 OCR하는 동안 진행률을 보여준다"""
            status.update(
                label=f"스캔본으로 보입니다 — OCR 진행 중… ({done}/{total} 페이지)"
            )

        try:
            doc_id = retriever_module.build_index(
                pdf_bytes, uploaded.name, progress=on_ocr_progress
            )
        except ValueError as error:
            status.update(label="색인 실패", state="error")
            st.error(str(error))
            st.stop()

        status.update(label="색인 완료", state="complete")

    st.session_state.doc_id = doc_id
    st.session_state.doc_name = uploaded.name

    stats = retriever_module.get_stats(doc_id)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("파일", stats["name"][:24])
    col2.metric("페이지 수", stats["page_count"])
    col3.metric("색인 청크 수", stats["chunk_count"])
    col4.metric("OCR 페이지", stats["ocr_page_count"])

    if stats["ocr_page_count"]:
        pages_label = ", ".join(f"p.{p}" for p in stats["ocr_pages"][:12])
        if stats["ocr_page_count"] > 12:
            pages_label += " …"
        st.caption(
            f"🔍 텍스트 레이어가 없어 OCR로 읽은 페이지: {pages_label} "
            "— 인식 오류가 섞일 수 있으니 문항의 원문 인용을 한 번 확인해주세요."
        )


# =====================================================================
# 출제 실행
# =====================================================================

def run_graph(counts: dict):
    """그래프를 스트리밍 실행하며 진행 상황을 보여준다"""

    config = {
        "configurable": {"thread_id": st.session_state.thread_id},
        "recursion_limit": 50,
    }

    payload = {
        "messages": [
            {
                "role": "user",
                "content": (
                    f"'{st.session_state.doc_name}' 문서로 "
                    f"객관식 {counts['mcq']}문항, 주관식 {counts['short']}문항, "
                    f"서술형 {counts['essay']}문항을 난이도 '{difficulty}'로 출제해주세요."
                ),
            }
        ],
        "doc_id": st.session_state.doc_id,
        "doc_name": st.session_state.doc_name,
        "counts": counts,
        "difficulty": difficulty,
        "retry_num": 0,
    }

    progress = st.status("출제를 시작합니다…", expanded=True)
    try:
        for chunk in st.session_state.graph.stream(payload, config, stream_mode="updates"):
            for node, value in chunk.items():
                progress.write(f"**{NODE_LABEL.get(node, node)}**")
                if value and value.get("messages"):
                    progress.caption(value["messages"][-1].content)
        progress.update(label="출제 완료", state="complete", expanded=False)
    except Exception as error:
        progress.update(label="출제 중 오류", state="error")
        st.error(f"에이전트 실행 중 오류가 발생했습니다: {error}")
        return

    # CHAP8: 체크포인트에서 최종 상태를 읽어온다
    st.session_state.result = st.session_state.graph.get_state(config).values


total = mcq_count + short_count + essay_count
ready = st.session_state.doc_id is not None and total > 0 and bool(api_key)

col_run, col_more = st.columns([1, 1])

with col_run:
    if st.button("🚀 문제 만들기", type="primary", disabled=not ready, use_container_width=True):
        st.session_state.result = None
        st.session_state.report = None
        st.session_state.thread_id = str(uuid.uuid4())  # 새 출제 세션
        run_graph({"mcq": mcq_count, "short": short_count, "essay": essay_count})

with col_more:
    has_result = bool(st.session_state.result)
    if st.button(
        "➕ 같은 문서로 이어서 더 만들기",
        disabled=not (has_result and ready),
        use_container_width=True,
        help="같은 thread_id를 재사용하므로 이미 만든 문항과 중복되지 않게 출제합니다.",
    ):
        st.session_state.report = None
        run_graph({"mcq": mcq_count, "short": short_count, "essay": essay_count})


# =====================================================================
# 풀이 모드
# =====================================================================

SOLVE_MODE = "📝 문제 풀기"
REVIEW_MODE = "📋 출제 결과 보기"

VERDICT_STYLE = {
    "정답": ("✅", st.success),
    "부분정답": ("🟡", st.warning),
    "오답": ("❌", st.error),
    "미응답": ("⬜", st.info),
}


def render_answer_sheet(mcqs, shorts, essays):
    """답안지 입력 폼. 제출하면 {키: 답} 딕셔너리를 반환한다"""

    with st.form("answer_sheet"):
        answers = {}
        number = 1

        for i, q in enumerate(mcqs):
            st.markdown(f"**{number}.** {q['question']}")
            choice = st.radio(
                "보기",
                options=list(range(4)),
                format_func=lambda j, q=q: f"{CIRCLED[j]} {strip_choice_prefix(q['choices'][j])}",
                index=None,
                key=f"in_mcq_{i}",
                label_visibility="collapsed",
            )
            answers[f"mcq_{i}"] = choice
            st.divider()
            number += 1

        for i, q in enumerate(shorts):
            st.markdown(f"**{number}.** {q['question']}")
            answers[f"short_{i}"] = st.text_input(
                "답", key=f"in_short_{i}", label_visibility="collapsed",
                placeholder="답을 입력하세요",
            )
            st.divider()
            number += 1

        for i, q in enumerate(essays):
            st.markdown(f"**{number}.** {q['question']}")
            answers[f"essay_{i}"] = st.text_area(
                "답", key=f"in_essay_{i}", height=140, label_visibility="collapsed",
                placeholder="답을 서술하세요",
            )
            st.divider()
            number += 1

        submitted = st.form_submit_button("📤 제출하고 채점받기", type="primary", use_container_width=True)

    return answers, submitted


def render_report(report):
    """채점 결과 표시"""

    total = report["total_score"]
    st.markdown(f"## 채점 결과 &nbsp; {total}점")

    cols = st.columns(4)
    cols[0].metric("총점", f"{total}점")
    cols[1].metric("맞힌 문항", f"{report['correct_count']} / {report['count']}")

    labels = {"mcq": "객관식", "short": "주관식", "essay": "서술형"}
    for col, (type_key, score) in zip(cols[2:], report["by_type"].items()):
        col.metric(labels[type_key], f"{score}점")

    st.progress(total / 100)
    st.divider()

    for i, item in enumerate(report["items"], 1):
        icon, box = VERDICT_STYLE.get(item["verdict"], ("📄", st.info))

        st.markdown(f"**{i}. {item['question']}**")

        if item["type"] == "essay":
            st.caption(f"{item['verdict']} · {item['score']}점")
        else:
            st.caption(f"{icon} {item['verdict']} · {item['score']}점")

        st.markdown(f"　**내 답**: {item['user_answer'] or '_(미응답)_'}")
        if item["verdict"] != "정답" and item["type"] != "essay":
            st.markdown(f"　**정답**: {item['correct_answer']}")

        box(item["feedback"])

        if item.get("missed_keywords"):
            st.caption(f"빠진 핵심어: {', '.join(item['missed_keywords'])}")

        if item.get("rubric_checks"):
            with st.expander("채점 기준별 평가"):
                for check in item["rubric_checks"]:
                    mark = "✅" if check["met"] else "⬜"
                    st.markdown(f"{mark} **{check['criterion']}** — {check['comment']}")
                st.divider()
                st.markdown("**모범 답안**")
                st.write(item["correct_answer"])

        st.caption(f"출처: p.{item['page']}")
        st.divider()


def render_solve(result, mcqs, shorts, essays):
    """풀이 모드 전체 흐름"""

    if not (mcqs or shorts or essays):
        st.info("풀 문항이 없습니다.")
        return

    # 이미 채점을 받았으면 결과 화면
    if st.session_state.get("report"):
        render_report(st.session_state.report)
        if st.button("🔄 다시 풀기", use_container_width=True):
            st.session_state.report = None
            st.rerun()
        return

    st.caption("답을 모두 채운 뒤 아래 제출 버튼을 누르세요. 주관식·서술형은 AI가 의미를 보고 채점합니다.")

    answers, submitted = render_answer_sheet(mcqs, shorts, essays)

    if submitted:
        progress = st.progress(0.0, text="채점 중…")

        def on_progress(done, total):
            progress.progress(done / total, text=f"채점 중… ({done}/{total})")

        try:
            st.session_state.report = grade_all(result, answers, on_progress=on_progress)
        except Exception as error:
            progress.empty()
            st.error(f"채점 중 오류가 발생했습니다: {error}")
            return

        progress.empty()
        st.rerun()


# =====================================================================
# 결과 표시
# =====================================================================

result = st.session_state.result

if result:
    st.divider()

    if result.get("doc_summary"):
        with st.expander("📚 문서 요약과 출제 주제", expanded=False):
            st.write(result["doc_summary"])
            if result.get("topics"):
                st.write("**출제 주제**")
                for topic in result["topics"]:
                    st.write(f"- {topic}")

    mcqs = result.get("mcqs", [])
    shorts = result.get("shorts", [])
    essays = result.get("essays", [])

    mode = st.radio(
        "모드",
        [SOLVE_MODE, REVIEW_MODE],
        horizontal=True,
        label_visibility="collapsed",
    )

if result and mode == SOLVE_MODE:
    render_solve(result, mcqs, shorts, essays)

elif result:
    show_answer = st.toggle("정답·해설 함께 보기", value=True)

    tab_mcq, tab_short, tab_essay, tab_log = st.tabs(
        [
            f"객관식 ({len(mcqs)})",
            f"주관식 ({len(shorts)})",
            f"서술형 ({len(essays)})",
            "검증 로그",
        ]
    )

    with tab_mcq:
        if not mcqs:
            st.info("객관식 문항이 없습니다.")
        for i, q in enumerate(mcqs, 1):
            st.markdown(f"**{i}. {q['question']}**")
            for j, choice in enumerate(q["choices"]):
                mark = "**" if (show_answer and j == q["answer_index"]) else ""
                st.markdown(f"　{CIRCLED[j]} {mark}{strip_choice_prefix(choice)}{mark}")
            if show_answer:
                st.success(f"정답: {CIRCLED[q['answer_index']]} · {q['explanation']}")
                st.caption(f"근거 (p.{q['page']}): \"{q['source_quote']}\"")
            st.divider()

    with tab_short:
        if not shorts:
            st.info("주관식 문항이 없습니다.")
        for i, q in enumerate(shorts, 1):
            st.markdown(f"**{i}. {q['question']}**")
            if show_answer:
                st.success(f"정답: {q['answer']}")
                st.caption(f"핵심어: {', '.join(q['keywords'])}")
                st.caption(f"해설: {q['explanation']}")
                st.caption(f"근거 (p.{q['page']}): \"{q['source_quote']}\"")
            st.divider()

    with tab_essay:
        if not essays:
            st.info("서술형 문항이 없습니다.")
        for i, q in enumerate(essays, 1):
            st.markdown(f"**{i}. {q['question']}**")
            if show_answer:
                with st.expander("모범 답안과 채점 기준"):
                    st.write(q["answer"])
                    st.write("**채점 기준**")
                    for item in q["rubric"]:
                        st.write(f"- {item}")
                    st.caption(f"근거 (p.{q['page']}): \"{q['source_quote']}\"")
            st.divider()

    with tab_log:
        rejected = result.get("rejected", [])
        if rejected:
            st.warning(f"근거 검증에서 제외된 문항 {len(rejected)}건")
            for item in rejected:
                st.write(f"- {item}")
        else:
            st.success("모든 문항이 근거 검증을 통과했습니다.")


if result:
    # ----- 내보내기 -----
    st.divider()
    base = os.path.splitext(result.get("doc_name", "quiz"))[0]

    d1, d2, d3 = st.columns(3)
    d1.download_button(
        "📥 문제지 (MD)",
        to_markdown(result, with_answers=False),
        file_name=f"{base}_문제지.md",
        mime="text/markdown",
        use_container_width=True,
    )
    d2.download_button(
        "📥 문제지+정답 (MD)",
        to_markdown(result, with_answers=True),
        file_name=f"{base}_문제와정답.md",
        mime="text/markdown",
        use_container_width=True,
    )
    d3.download_button(
        "📥 JSON",
        to_json(result),
        file_name=f"{base}_quiz.json",
        mime="application/json",
        use_container_width=True,
    )

elif st.session_state.doc_id:
    st.info("사이드바에서 문항 수를 정하고 **문제 만들기**를 눌러주세요.")
else:
    st.info("PDF를 업로드하면 시작합니다.")
    with st.expander("어떻게 동작하나요?"):
        st.markdown(
            f"""
            1. **문서 색인** — PDF를 페이지 단위로 읽어 청킹하고 임베딩합니다. *(CHAP6 rag_agent)*
            2. **출제 계획** — 문서를 요약하고 출제 주제를 뽑습니다. *(CHAP7 planning agent)*
            3. **에이전트 배정** — 슈퍼바이저가 Router 도구로 담당 에이전트를 고릅니다. *(CHAP7 supervisor)*
            4. **출제** — {' · '.join(QUESTION_TYPES.values())} 에이전트가 검색된 발췌문만 근거로 문항을 만듭니다.
            5. **근거 검증** — 문서에 없는 내용을 지어낸 문항을 걸러내고 부족분을 재출제합니다. *(CHAP6 환각 검사)*
            6. **세션 유지** — 체크포인터가 상태를 기억해 '이어서 더 만들기'가 중복 없이 동작합니다. *(CHAP8)*
            """
        )
