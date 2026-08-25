from apps.applications.services.ats_keyword_extractor import AtsKeywordExtractor
from apps.applications.services.cover_letter_layout import (
    merge_letter_text,
    normalize_letter_text,
    parse_letter,
    strip_html,
)


GOLDEN = """
WEN-YEN (HANK) HSU
Los Angeles, CA | +1 (213) 536-3478 | godhanko@gmail.com | LinkedIn/wenyenhsu
August 19, 2026

Rippling
Machine Learning Team
San Francisco, CA
Dear Rippling Hiring Team:
I am writing to apply for the Machine Learning Intern position at Rippling.
At the USC NLP Group, my research focuses on multimodal AI agents.
My previous engineering experience at TSMC and Entegris provides a foundation.
The opportunity to contribute to Rippling is particularly compelling.
Best regards,
Wen-Yen (Hank) Hsu
"""


def test_parse_letter_keeps_header_recipient_and_body_separate():
    parts = parse_letter(GOLDEN)

    assert parts["name"] == "WEN-YEN (HANK) HSU"
    assert "godhanko@gmail.com" in parts["contact"]
    assert parts["date"] == "August 19, 2026"
    assert parts["recipient"][0] == "Rippling"
    assert parts["greeting"] == "Dear Rippling Hiring Team:"
    assert len(parts["body"]) == 4
    assert parts["closing"] == "Best regards,"
    assert parts["signature"] == ["Wen-Yen (Hank) Hsu"]


def test_normalize_restores_mashed_header_and_drops_cover_letter_title():
    mashed = (
        "Cover Letter HANK HSU Los Angeles, CA | godhanko@gmail.com "
        "August 19, 2026 Crowe Global Professional Services Inc. San Francisco, CA "
        "Dear Crowe Hiring Team: I am writing about Kubernetes. "
        "Best regards, Wen-Yen (Hank) Hsu"
    )

    text = normalize_letter_text(mashed)
    parts = parse_letter(text)

    assert "Cover Letter" not in parts["name"]
    assert parts["name"] == "HANK HSU"
    assert parts["contact"].startswith("Los Angeles")
    assert parts["date"] == "August 19, 2026"
    assert parts["recipient"][0].startswith("Crowe")
    assert parts["recipient"][-1] == "San Francisco, CA"
    assert parts["greeting"] == "Dear Crowe Hiring Team:"
    assert "Kubernetes" in " ".join(parts["body"])
    assert parts["closing"] == "Best regards,"


def test_merge_keeps_original_header_and_uses_rewritten_body():
    rewritten = (
        "HANK HSU Los Angeles, CA | other@example.com August 19, 2026 "
        "Crowe AI Team San Francisco, CA Dear Crowe Hiring Team: "
        "I am writing about Kubernetes and Python. Best regards, Someone Else"
    )

    merged = merge_letter_text(GOLDEN, rewritten, company="Crowe")
    parts = parse_letter(merged)

    assert parts["name"] == "WEN-YEN (HANK) HSU"
    assert "godhanko@gmail.com" in parts["contact"]
    assert parts["greeting"] == "Dear Crowe Hiring Team:"
    assert "Kubernetes" in " ".join(parts["body"])
    assert parts["recipient"][-1] == "San Francisco, CA"
    assert parts["signature"] == ["Wen-Yen (Hank) Hsu"]
    assert merged.splitlines()[0] == "WEN-YEN (HANK) HSU"
    assert "Cover Letter" not in merged


def test_merge_retargets_when_model_copies_the_original_letter():
    merged = merge_letter_text(
        GOLDEN,
        GOLDEN,
        company="Crowe",
        job_title="AI Functional Intern",
    )
    parts = parse_letter(merged)

    assert parts["recipient"][0] == "Crowe"
    assert parts["greeting"] == "Dear Crowe Hiring Team:"
    assert "Rippling" not in merged
    assert "Crowe" in " ".join(parts["body"])
    assert "AI Functional Intern" in " ".join(parts["body"])
    assert parts["name"] == "WEN-YEN (HANK) HSU"


def test_merge_unstructured_copy_keeps_rewritten_text():
    merged = merge_letter_text(
        "template Cover_Letter_AI.docx",
        "Tailored cover letter about Kubernetes.",
    )

    assert merged == "Tailored cover letter about Kubernetes."


def test_strip_html_removes_markup_from_job_description():
    assert strip_html("<p>Need <b>Kubernetes</b> and Python.</p>") == (
        "Need Kubernetes and Python."
    )


def test_payload_text_keeps_newlines_and_paragraphs_array():
    text = AtsKeywordExtractor._payload_text(
        {"text": "Dear Team:\\n\\nI am writing about Kubernetes."}
    )
    assert "\n\n" in text
    assert "Kubernetes" in text

    from_list = AtsKeywordExtractor._payload_text(
        {"paragraphs": ["Dear Team:", "I am writing about Kubernetes."]}
    )
    assert "Dear Team:" in from_list
    assert "Kubernetes" in from_list


def test_cover_letter_prompt_asks_to_keep_layout():
    prompt = AtsKeywordExtractor()._build_cover_letter_prompt(
        "Intern", "Crowe", GOLDEN, "<p>Need Kubernetes</p>"
    )

    assert "Retarget" in prompt
    assert "Do not keep the previous company" in prompt
    assert "Do not add a title" in prompt
