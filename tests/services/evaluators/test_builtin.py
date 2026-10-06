from app.services.evaluators.builtin import build_judge_prompt, parse_judge_output

CONTEXT = [{"number": 1, "content": "Error E-4711 means the upstream certificate expired."}]


def _format_line(messages) -> str:
    return next(line for line in messages[-1].content.splitlines() if line.startswith("Return exactly:"))


def test_with_a_reference_the_judge_is_asked_for_a_recall_number_not_null():
    # Offered "number or null", ministral-8b-latest answered null although a
    # reference was given, so the evaluation had no context recall.
    line = _format_line(build_judge_prompt("Q?", CONTEXT, "It expired [1].", "The certificate expired."))
    assert '"context_recall": number,' in line and "null" not in line
    line = _format_line(build_judge_prompt("Q?", CONTEXT, "It expired [1].", None))
    assert '"context_recall": null,' in line


def test_ministral_s_fenced_reply_is_read():
    # ministral-8b-latest's real reply to the prompt above, with a reference.
    reply = (
        '```json\n{\n  "faithfulness": 1.0,\n  "answer_relevancy": 0.8,\n  "context_precision": 1.0,\n'
        '  "context_recall": 1.0,\n  "rationale": "The answer is fully faithful to the context."\n}\n```'
    )
    scores = parse_judge_output(reply, has_reference=True)
    assert (scores.faithfulness, scores.answer_relevancy, scores.context_precision, scores.context_recall) == (1.0, 0.8, 1.0, 1.0)
