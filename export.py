"""출제 결과를 배포 가능한 형식으로 변환"""

import json
from typing import List

from settings import strip_choice_prefix

CIRCLED = ["①", "②", "③", "④", "⑤"]


def to_markdown(state: dict, with_answers: bool = True) -> str:
    """문제지(+정답지) 마크다운 생성"""

    lines: List[str] = []
    doc_name = state.get("doc_name", "문서")
    lines.append(f"# {doc_name} 문제지")
    lines.append("")
    if state.get("doc_summary"):
        lines.append(f"> {state['doc_summary']}")
        lines.append("")
    lines.append(f"- 난이도: {state.get('difficulty', '중')}")
    lines.append(
        f"- 문항 수: 객관식 {len(state.get('mcqs', []))} / "
        f"주관식 {len(state.get('shorts', []))} / 서술형 {len(state.get('essays', []))}"
    )
    lines.append("")

    number = 1

    mcqs = state.get("mcqs", [])
    if mcqs:
        lines.append("## 객관식")
        lines.append("")
        for q in mcqs:
            lines.append(f"**{number}.** {q['question']}")
            lines.append("")
            for i, choice in enumerate(q["choices"]):
                lines.append(f"{CIRCLED[i]} {strip_choice_prefix(choice)}")
            lines.append("")
            number += 1

    shorts = state.get("shorts", [])
    if shorts:
        lines.append("## 주관식")
        lines.append("")
        for q in shorts:
            lines.append(f"**{number}.** {q['question']}")
            lines.append("")
            lines.append("답: ______________________________")
            lines.append("")
            number += 1

    essays = state.get("essays", [])
    if essays:
        lines.append("## 서술형")
        lines.append("")
        for q in essays:
            lines.append(f"**{number}.** {q['question']}")
            lines.append("")
            number += 1

    if not with_answers:
        return "\n".join(lines)

    # ----- 정답지 -----
    lines.append("---")
    lines.append("")
    lines.append("# 정답 및 해설")
    lines.append("")

    number = 1
    for q in mcqs:
        answer = CIRCLED[q["answer_index"]]
        lines.append(f"**{number}. 정답: {answer} {strip_choice_prefix(q['choices'][q['answer_index']])}**")
        lines.append("")
        lines.append(f"- 해설: {q['explanation']}")
        lines.append(f"- 근거 (p.{q['page']}): \"{q['source_quote']}\"")
        lines.append("")
        number += 1

    for q in shorts:
        lines.append(f"**{number}. 정답: {q['answer']}**")
        lines.append("")
        lines.append(f"- 핵심어: {', '.join(q['keywords'])}")
        lines.append(f"- 해설: {q['explanation']}")
        lines.append(f"- 근거 (p.{q['page']}): \"{q['source_quote']}\"")
        lines.append("")
        number += 1

    for q in essays:
        lines.append(f"**{number}. 모범 답안**")
        lines.append("")
        lines.append(q["answer"])
        lines.append("")
        lines.append("- 채점 기준")
        for item in q["rubric"]:
            lines.append(f"  - {item}")
        lines.append(f"- 근거 (p.{q['page']}): \"{q['source_quote']}\"")
        lines.append("")
        number += 1

    return "\n".join(lines)


def to_json(state: dict) -> str:
    """LMS 연동 등을 위한 JSON 내보내기"""

    payload = {
        "document": state.get("doc_name"),
        "summary": state.get("doc_summary"),
        "difficulty": state.get("difficulty"),
        "topics": state.get("topics", []),
        "questions": {
            "multiple_choice": state.get("mcqs", []),
            "short_answer": state.get("shorts", []),
            "essay": state.get("essays", []),
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
