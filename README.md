# 📝 PDF 문제 출제기

PDF를 업로드하면 **객관식 · 주관식 · 서술형** 문제를 문서 근거(페이지 + 원문 인용)와 함께 만들어 주는 Streamlit 사이트.
PART2와 CHAP6~8에서 배운 패턴을 실제로 조합해 만들었다.

## 실행

```bash
# 1) 의존성 (루트 venv 기준, 이미 설치되어 있음)
venv/Scripts/python.exe -m pip install -r quiz_generator/requirements.txt

# 2) API 키
cp quiz_generator/.env.example quiz_generator/.env
#   .env 안에 OPENAI_API_KEY=sk-... 입력

# 3) 실행
venv/Scripts/python.exe -m streamlit run quiz_generator/app.py
```

그래프 구조만 확인하려면:

```bash
cd quiz_generator && ../venv/Scripts/python.exe make_graph.py   # graph.png 생성
```

## 그래프 구조

```
START → planning → supervisor ─┬→ mcq   ─┐
                               ├→ short ─┼→ validate ─┬→ (부족하면 같은 에이전트로 재출제)
                               └→ essay ─┘            └→ supervisor → … → END
```

| 노드 | 역할 |
|---|---|
| `planning` | 문서를 요약하고 출제 주제 3~6개를 뽑아 유형별 작업 목록(`plan`)을 만든다 |
| `supervisor` | `Router` 도구로 현재 작업을 담당할 출제 에이전트를 고른다. `plan`이 비면 END |
| `mcq` / `short` / `essay` | 주제로 검색한 발췌문**만** 근거로 구조화 출력(Pydantic) 문항을 생성 |
| `validate` | 문항별로 "발췌문에 근거하는가"를 이진 채점. 탈락분은 버리고 부족하면 재출제 |

재시도는 유형당 최대 2회(`nodes.MAX_RETRY`). 소진하면 확보한 문항만 가지고 다음 유형으로 넘어간다.

## 두 가지 모드

결과가 나오면 화면 위에서 모드를 고를 수 있다.

### 📝 문제 풀기
정답을 가린 채 답안지를 푼다. 객관식은 보기 선택, 주관식은 한 줄 입력, 서술형은 텍스트 영역.
**제출하고 채점받기**를 누르면 채점 결과가 나온다.

| 유형 | 채점 방식 |
|---|---|
| 객관식 | 보기 인덱스 비교 — LLM 호출 없음, 즉시 |
| 주관식 | LLM이 모범답안·핵심어와 대조해 **정답 / 부분정답 / 오답** 판정. 표현이 달라도 의미가 같으면 정답, 맞춤법은 감점 없음 |
| 서술형 | LLM이 **채점 기준 항목별로** 충족 여부를 판정하고 0~100점 + 잘한 점/보완할 점 |

총점, 유형별 점수, 문항별 판정과 피드백, 근거 페이지가 함께 표시된다. 미응답은 LLM을 호출하지 않고 0점 처리한다.

### 📋 출제 결과 보기
출제자용 검토 화면. 정답·해설·근거를 토글로 켜고 끄며 문항 품질을 확인하고, 검증 로그로 걸러진 문항을 본다.

내보내기 버튼은 두 모드 모두에서 보인다.

## 파일 구성

| 파일 | 내용 | 참고한 챕터 |
|---|---|---|
| `app.py` | Streamlit UI (업로드 / 옵션 / 진행 상황 / 결과 탭 / 내보내기) | PART2 `app.py` |
| `retriever.py` | PDF → 페이지 분해(+OCR 폴백) → 청킹 → 벡터 색인 → 검색 | CHAP6 `rag_agent/retriever.py` |
| `ocr_server.py` | 스캔 PDF OCR MCP 서버 (stdio) — `pdf_probe`, `pdf_ocr` 도구 | CHAP9 `mcp_agent/server.py` |
| `ocr_client.py` | OCR MCP 서버를 호출하는 동기 클라이언트 | CHAP9 `mcp_agent/client.py` |
| `state.py` | `MessagesState` 확장 상태 | CHAP6 `rag_agent/state.py`, CHAP7 `settings.py` |
| `schemas.py` | `QuizPlan`, `MCQ`, `ShortAnswer`, `Essay`, `Grade` | CHAP6 `edges.py`, CHAP7 `planning_agent.py` |
| `settings.py` | 모델 팩토리와 시스템 프롬프트 | CHAP7 `settings.py` |
| `nodes.py` | planning / supervisor / 출제 3종 / validate | CHAP6 `nodes.py`, CHAP7 `supervisor_agent.py` |
| `edges.py` | 검증 후 라우팅 함수 | CHAP6 `edges.py` |
| `make_graph.py` | 그래프 조립 + 체크포인터 | CHAP7 `make_graph.py`, CHAP8 |
| `grading.py` | 사용자 답안 채점 (주관식·서술형은 LLM 구조화 출력) | CHAP6 `edges.py` 평가자 |
| `export.py` | 문제지/정답지 Markdown, JSON 내보내기 | — |

## 챕터 패턴이 어디에 쓰였나

**PART2 — Streamlit 챗봇 골격**
`st.session_state`로 상태 보관, `st.secrets` → `.env` 순으로 키 조회, 업로드 → 실행 → 결과 표시 흐름.

**CHAP6 — 단일 에이전트 / RAG**
- `retriever.py`: 문서를 청킹해 임베딩하고 `as_retriever(search_kwargs={"k": ...})`로 검색 — `rag_agent/retriever.py`와 같은 구조.
- `retrieve_context()`: 검색 결과를 페이지 순으로 정리해 넘기는 것은 `retrieve` + `context_organizer`를 하나로 합친 것.
- `validate_node` + `edges.decide_after_validate`: `check_hallucinations`의 이진 채점과 재시도 루프, `retry_num` 상한까지 동일한 아이디어.
- 프롬프트에 "발췌문에 없는 내용을 지어내지 말 것 + 원문 인용 + 페이지 표기"를 강제하는 것도 RAG 챕터의 출처 명시 규칙에서 가져왔다.

**CHAP7 — 멀티 에이전트 (Supervisor)**
- `Router` TypedDict + `llm.bind_tools([Router])` + `Command(goto=...)` — `supervisor_agent_web/supervisor_agent.py` 그대로.
- `planning_node`가 계획을 세우고 supervisor가 `plan[0]`만 처리한 뒤 되돌아오는 구조 — `supervisor_planning_agent`의 planning ↔ supervisor 왕복.
- `add_node(..., destinations=(...))`로 Command 목적지를 선언 — `supervisor_planning_agent/make_graph.py`.
- 각 에이전트가 자기 `system_prompt`를 갖고 결과 메시지에 `name`을 붙이는 것도 같은 패턴.

**CHAP8 — 단기 메모리**
- `InMemorySaver` + `thread_id` 하나 = 출제 세션 하나.
- **이어서 더 만들기**: 같은 `thread_id`로 다시 실행하면 체크포인트에 남아 있던 기존 문항을 읽어, 부족분만 생성하고 프롬프트에 "이미 출제된 문항(중복 금지)"으로 넣어 준다. 단기 메모리가 실제로 결과를 바꾸는 지점.
- 사이드바 **세션 초기화**는 `checkpointer.delete_thread(thread_id)` — CHAP8 "체크포인트 관리" 절 그대로.

## 스캔 PDF OCR (CHAP9 MCP 패턴)

텍스트 레이어가 없는 페이지는 OCR을 거쳐 색인된다. OCR 기능은 별도 MCP 서버로 분리돼 있다.

```
app.py → retriever.build_index
           └─ extract_text_layer (pypdf)        # 페이지별 텍스트 확인
              └─ 빈 페이지가 있으면
                 ocr_client.ocr_pdf             # stdio MCP 클라이언트
                   └─ ocr_server.py (자식 프로세스)
                        pdf_probe  : 텍스트 레이어 유무 조사
                        pdf_ocr    : PyMuPDF 렌더링 → gpt-4o 비전 전사
```

| 항목 | 값 |
|---|---|
| 엔진 | PyMuPDF 렌더링 + `gpt-4o` 비전 (`OCR_MODEL` 환경 변수로 교체 가능) |
| 별도 설치 | 없음 — Tesseract/poppler 불필요, 기존 `OPENAI_API_KEY` 재사용 |
| 해상도 | 200 DPI (`ocr_server.RENDER_DPI`) |
| 동시 호출 | 4 (`MAX_CONCURRENCY`) |
| 한도 | 한 번에 40페이지 (`MAX_OCR_PAGES`) — 비용 안전장치 |
| 비용 | 페이지당 gpt-4o 비전 1회. 스캔 10페이지 ≈ $0.1 내외 |

화면에는 OCR로 읽은 페이지 수가 지표로 뜨고, 어떤 페이지였는지 캡션으로 표시된다.

**구현하면서 걸렸던 것**

- **stdout은 프로토콜 채널이다.** stdio MCP에서 서버의 stdout은 JSON-RPC 전용이다. PyMuPDF는 경고를 **기본적으로 stdout에 찍기 때문에**(폰트 인코딩 미지원, xref 손상 등 특정 PDF에서만 발생) 그대로 두면 응답 줄에 경고가 달라붙어 세션이 끊긴다. 증상은 `unhandled errors in a TaskGroup (1 sub-exception)` — 원인이 전혀 드러나지 않는다.
  ```
  input_value='MuPDF error: bad font{"jsonrpc":"2.0",...}'
                                    ↑ 응답이 경고 뒤에 붙어 파싱 실패
  ```
  `import pymupdf` **전에** `PYMUPDF_MESSAGE=fd:2`를 설정하고, `set_messages(fd=2)` + `TOOLS.mupdf_display_errors(False)`로 이중 차단한다 (`ocr_server.py` 상단). PDF에 따라 성공/실패가 갈린다면 이걸 의심할 것.
- Windows에서 stdio MCP 서버는 자식 프로세스로 뜬다. `WindowsSelectorEventLoopPolicy`를 쓰면 `subprocess`를 지원하지 않아 서버가 뜨지 않는다 → **Proactor 루프**를 쓴다 (`ocr_client.py`).
- **anyio의 `ExceptionGroup`은 원인을 감춘다.** `describe_error()`로 하위 예외를 풀어내고, 서버 stderr를 `ocr_server.log`로 받아 에러 메시지에 함께 붙인다.
- `stdio_client`의 기본 환경은 안전한 최소 집합이라 `OPENAI_API_KEY`가 서버까지 가지 않는다 → `StdioServerParameters(env=dict(os.environ))`로 현재 환경을 넘긴다.
- `mcp` 2.x는 `FastMCP`가 `MCPServer`로 바뀌어 CHAP9 코드와 호환되지 않는다 → `mcp>=1.19,<2`로 고정.
- 서버는 `sys.executable`로 띄운다. `"python"`으로 쓰면 가상환경 밖 인터프리터가 잡혀 import 에러가 난다.

**한계**

- PDF가 텍스트 레이어를 갖고 있지만 인코딩이 깨져 글자가 뭉개지는 경우(예: `/UniKS-UTF16-H`)는 "텍스트가 있다"고 판정돼 OCR이 돌지 않는다. 이런 파일은 강제로 OCR을 태워야 한다.

## 알아두면 좋은 점

- **스캔 이미지 PDF도 읽는다.** `pypdf`가 텍스트를 못 뽑은 페이지만 골라 OCR MCP 서버로 넘긴다(아래 "스캔 PDF OCR" 참고). 텍스트 페이지와 스캔 페이지가 섞여 있어도 스캔 페이지에만 OCR이 돈다.
- **벡터스토어는 인메모리다.** 프로세스가 죽으면 색인이 사라진다. CHAP6처럼 영속화하려면 `retriever.build_index`의 `InMemoryVectorStore`를 `Chroma(persist_directory=...)`로 바꾸면 된다(나머지 코드는 그대로).
- **비용**: 출제는 문서 색인(임베딩) 1회 + planning 1회 + 유형당 생성 1회 + 문항당 검증 1회(gpt-4o-mini). 채점은 주관식 1문항당 gpt-4o-mini 1회, 서술형 1문항당 gpt-4o 1회(객관식은 0회). 10문항 기준 출제 4~5회 + 채점 5회 정도.
- `langgraph.json`이 있으므로 `langgraph dev`로도 띄울 수 있다.

## 더 붙일 만한 것

- 오답 노트: 채점에서 틀린 문항의 주제로 재검색해 유사 문항 재출제
- 채점 이력: 여러 번 푼 점수 변화를 체크포인터에 누적 (CHAP8)
- 문항 은행: 결과 JSON을 DB에 적재 (CHAP7 `supervisor_agent_web/database_agent.py` 패턴)
- 웹 검색 보강: 문서 밖 최신 사례를 덧붙인 응용 문항 (CHAP7 `web_agent`)
