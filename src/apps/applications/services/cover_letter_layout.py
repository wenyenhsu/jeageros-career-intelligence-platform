"""Keep cover-letter paragraph structure when rewriting from a JD."""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_MONTH_RE = "|".join(_MONTHS + tuple(month[:3] for month in _MONTHS))
DATE_RE = re.compile(rf"^(?:{_MONTH_RE})\.?\s+\d{{1,2}},\s+\d{{4}}$", re.I)
GREETING_RE = re.compile(r"^(dear|to whom)\b", re.I)
CLOSING_RE = re.compile(
    r"^(best regards|kind regards|warm regards|sincerely|respectfully|"
    r"yours truly|thank you)\s*,?\s*$",
    re.I,
)
TITLE_RE = re.compile(r"^cover\s*letter\.?$", re.I)
LOCATION_RE = re.compile(
    r"^(?:[A-Z][a-z]+(?:[\s.-][A-Z][a-z]+)*|[A-Z]{2}),\s*[A-Z]{2}$"
)
CITY_STATE_IN_LINE_RE = re.compile(
    r"\s+((?:[A-Z][a-z]+(?:[\s.-][A-Z][a-z]+)?),\s*[A-Z]{2})$"
)
CONTACT_RE = re.compile(r"[|@]|linkedin|github|portfolio", re.I)
HTML_TAG_RE = re.compile(r"(?s)<[^>]+>")
HTML_BLOCK_RE = re.compile(r"(?is)<(script|style)[^>]*>.*?</\1>")


def strip_html(text):
    value = HTML_BLOCK_RE.sub(" ", str(text or ""))
    value = HTML_TAG_RE.sub(" ", value)
    value = (
        value.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def unescape_newlines(text):
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if "\n" not in value and "\\n" in value:
        value = value.replace("\\n", "\n")
    return value.replace("\u00a0", " ")


def restore_letter_linebreaks(text):
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value:
        return ""
    value = re.sub(
        rf"\s+((?:{_MONTH_RE})\.?\s+\d{{1,2}},\s+\d{{4}})(?=\s|$)",
        r"\n\1\n",
        value,
        flags=re.I,
    )
    value = re.sub(r"\s+(Dear\s+[^:]+:)\s+", r"\n\1\n", value, flags=re.I)
    value = re.sub(r"\s+(To whom it may concern:)\s+", r"\n\1\n", value, flags=re.I)
    value = re.sub(
        r"\s+((?:Best regards|Kind regards|Warm regards|Sincerely|"
        r"Respectfully|Yours truly|Thank you)\s*,)",
        r"\n\1\n",
        value,
        flags=re.I,
    )
    return value.strip()


def normalize_letter_text(text):
    value = unescape_newlines(text).strip()
    value = re.sub(r"^```(?:\w+)?\s*|\s*```$", "", value).strip()
    lines = [line.rstrip() for line in value.split("\n")]
    while lines and TITLE_RE.match(lines[0].strip()):
        lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)
    if lines:
        lines[0] = re.sub(
            r"^cover\s*letter[:.\s-]+", "", lines[0], flags=re.I
        ).strip()
    value = "\n".join(lines).strip()
    if value and "\n" not in value:
        value = restore_letter_linebreaks(value)
    lines = []
    for raw in value.split("\n"):
        line = " ".join(raw.split())
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        lines.extend(_split_header_line(line))
    value = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", value)


def _split_header_line(line):
    match = re.match(
        r"^((?:[A-Z][A-Z'.\-()]+(?:\s+(?:[A-Z][A-Z'.\-()]+|\([A-Z][A-Z'.\-()]*\))){1,6}))"
        r"\s+(.+\|.+)$",
        line,
    )
    if match:
        return [match.group(1).strip(), match.group(2).strip()]
    location = CITY_STATE_IN_LINE_RE.search(line)
    if (
        location
        and not CONTACT_RE.search(line)
        and not GREETING_RE.match(line)
        and location.start() > 8
    ):
        company = line[: location.start()].strip()
        if company:
            return [company, location.group(1).strip()]
    return [line]


def _nonempty(lines):
    return [(index, line.strip()) for index, line in enumerate(lines) if line.strip()]


def parse_letter(text):
    lines = normalize_letter_text(text).split("\n") if str(text or "").strip() else []
    parts = {
        "name": "",
        "contact": "",
        "date": "",
        "recipient": [],
        "greeting": "",
        "body": [],
        "closing": "",
        "signature": [],
    }
    items = _nonempty(lines)
    if not items:
        return parts

    greeting_at = next(
        (index for index, (_, line) in enumerate(items) if GREETING_RE.match(line)),
        None,
    )
    closing_at = next(
        (index for index, (_, line) in enumerate(items) if CLOSING_RE.match(line)),
        None,
    )
    date_at = next(
        (index for index, (_, line) in enumerate(items) if DATE_RE.match(line)),
        None,
    )

    header_end = greeting_at if greeting_at is not None else len(items)
    header = items[:header_end]
    if header:
        parts["name"] = header[0][1]
    for _, line in header[1:]:
        if not parts["contact"] and CONTACT_RE.search(line):
            parts["contact"] = line
        elif DATE_RE.match(line):
            parts["date"] = line
        elif line != parts["name"]:
            parts["recipient"].append(line)

    if greeting_at is not None:
        parts["greeting"] = items[greeting_at][1]
    body_start = 0 if greeting_at is None else greeting_at + 1
    body_end = closing_at if closing_at is not None else len(items)
    parts["body"] = [line for _, line in items[body_start:body_end]]
    if closing_at is not None:
        parts["closing"] = items[closing_at][1]
        parts["signature"] = [line for _, line in items[closing_at + 1 :]]
    if not parts["date"] and date_at is not None:
        parts["date"] = items[date_at][1]
        parts["recipient"] = [
            line for line in parts["recipient"] if not DATE_RE.match(line)
        ]
    parts["body"] = split_body_paragraphs(parts["body"])
    return parts


def split_body_paragraphs(paragraphs, target=4):
    values = [str(item).strip() for item in paragraphs if str(item).strip()]
    if len(values) == 1 and len(values[0]) > 480:
        sentences = [
            piece.strip()
            for piece in re.split(r"(?<=[.!?])\s+", values[0])
            if piece.strip()
        ]
        if len(sentences) >= target:
            size = max(1, (len(sentences) + target - 1) // target)
            chunks = []
            for index in range(0, len(sentences), size):
                chunks.append(" ".join(sentences[index : index + size]))
            return chunks[: target + 1]
    return values


def format_letter(parts):
    parts = parts or {}
    blocks = []
    for key in ("name", "contact", "date"):
        value = str(parts.get(key) or "").strip()
        if value:
            blocks.append(value)
    recipient = [
        str(line).strip() for line in (parts.get("recipient") or []) if str(line).strip()
    ]
    greeting = str(parts.get("greeting") or "").strip()
    body = [str(line).strip() for line in (parts.get("body") or []) if str(line).strip()]
    closing = str(parts.get("closing") or "").strip()
    signature = [
        str(line).strip() for line in (parts.get("signature") or []) if str(line).strip()
    ]
    if recipient or greeting or body:
        if blocks:
            blocks.append("")
        blocks.extend(recipient)
        if greeting:
            if recipient:
                blocks.append("")
            blocks.append(greeting)
        for paragraph in body:
            blocks.append("")
            blocks.append(paragraph)
        if closing or signature:
            blocks.append("")
            if closing:
                blocks.append(closing)
            blocks.extend(signature)
    return "\n".join(blocks).strip() + ("\n" if blocks else "")


def _company_in(text, company):
    name = str(company or "").strip()
    if len(name) < 3:
        return False
    return re.search(rf"\b{re.escape(name)}\b", str(text or ""), re.I) is not None


def _location_lines(lines):
    return [
        line for line in lines or [] if LOCATION_RE.match(str(line or "").strip())
    ]


def _retarget_text(text, old_company, new_company, new_title=""):
    updated = str(text or "")
    if old_company and new_company and old_company.casefold() != new_company.casefold():
        updated = re.sub(rf"\b{re.escape(old_company)}\b", new_company, updated)
    if new_title:
        updated = re.sub(
            r"(apply for the )(.+?)( position at )",
            rf"\1{new_title}\3",
            updated,
            count=1,
            flags=re.I,
        )
    return updated


def _recipient_for_job(
    company, rewritten_recipient, original_recipient, old_company="", job_title=""
):
    rewritten_recipient = [
        str(line).strip()
        for line in (rewritten_recipient or [])
        if str(line).strip()
    ]
    original_recipient = [
        str(line).strip()
        for line in (original_recipient or [])
        if str(line).strip()
    ]
    blob = " ".join(rewritten_recipient)
    locations = _location_lines(rewritten_recipient) or _location_lines(
        original_recipient
    )
    copied_old = bool(
        company
        and old_company
        and rewritten_recipient
        and _company_in(blob, old_company)
        and not _company_in(blob, company)
    )
    if rewritten_recipient and not copied_old:
        if not company or _company_in(blob, company):
            return _clean_recipient(rewritten_recipient, company, job_title)
        if not old_company or not _company_in(blob, old_company):
            return _clean_recipient(rewritten_recipient, company, job_title)
    if company:
        return [company] + [
            line for line in locations if line.casefold() != company.casefold()
        ]
    return rewritten_recipient or original_recipient


def _clean_recipient(lines, company, job_title=""):
    cleaned = []
    title = str(job_title or "").strip()
    for line in lines:
        if title and title.casefold() in line.casefold() and "team" in line.casefold():
            continue
        cleaned.append(line)
    if company and not _company_in(" ".join(cleaned), company):
        cleaned = [company] + [
            line for line in cleaned if line.casefold() != company.casefold()
        ]
    return cleaned or lines


def merge_letter_text(original_text, rewritten_text, *, company="", job_title=""):
    original = parse_letter(original_text)
    rewritten = parse_letter(rewritten_text)
    original_is_letter = bool(original["greeting"] and original["body"])
    if not original_is_letter:
        return normalize_letter_text(rewritten_text)

    old_company = original["recipient"][0] if original["recipient"] else ""
    recipient = _recipient_for_job(
        company,
        rewritten["recipient"],
        original["recipient"],
        old_company=old_company,
        job_title=job_title,
    )
    if company and (
        not rewritten["greeting"] or not _company_in(rewritten["greeting"], company)
    ):
        greeting = f"Dear {company} Hiring Team:"
    else:
        greeting = rewritten["greeting"] or original["greeting"]

    body = rewritten["body"]
    if not body:
        blob = normalize_letter_text(rewritten_text)
        if blob and not GREETING_RE.match(blob):
            body = split_body_paragraphs([blob])
        else:
            body = list(original["body"])
    if company and body:
        blob = " ".join(body)
        copied_old_employer = bool(
            old_company
            and _company_in(blob, old_company)
            and not _company_in(blob, company)
        )
        if copied_old_employer:
            body = [
                _retarget_text(paragraph, old_company, company, job_title)
                for paragraph in body
            ]
    merged = {
        "name": original["name"] or rewritten["name"],
        "contact": original["contact"] or rewritten["contact"],
        "date": original["date"] or rewritten["date"],
        "recipient": recipient,
        "greeting": greeting,
        "body": body or original["body"],
        "closing": rewritten["closing"] or original["closing"] or "Best regards,",
        "signature": original["signature"] or rewritten["signature"],
    }
    return format_letter(merged)


def letter_slot_indexes(texts):
    items = [
        (index, str(line or "").strip())
        for index, line in enumerate(texts or [])
        if str(line or "").strip()
    ]
    slots = {
        "name": None,
        "contact": None,
        "date": None,
        "recipient": [],
        "greeting": None,
        "body": [],
        "closing": None,
        "signature": [],
    }
    if not items:
        return slots
    greeting_at = next(
        (index for index, (_, line) in enumerate(items) if GREETING_RE.match(line)),
        None,
    )
    closing_at = next(
        (index for index, (_, line) in enumerate(items) if CLOSING_RE.match(line)),
        None,
    )
    header_end = greeting_at if greeting_at is not None else 0
    header = items[:header_end]
    if header:
        slots["name"] = header[0][0]
    for para_index, line in header[1:]:
        if slots["contact"] is None and CONTACT_RE.search(line):
            slots["contact"] = para_index
        elif DATE_RE.match(line):
            slots["date"] = para_index
        else:
            slots["recipient"].append(para_index)
    if greeting_at is not None:
        slots["greeting"] = items[greeting_at][0]
        body_start = greeting_at + 1
        body_end = closing_at if closing_at is not None else len(items)
        slots["body"] = [items[index][0] for index in range(body_start, body_end)]
    if closing_at is not None:
        slots["closing"] = items[closing_at][0]
        slots["signature"] = [items[index][0] for index in range(closing_at + 1, len(items))]
    return slots


def read_cover_letter_text(path):
    path = Path(path)
    suffix = path.suffix.casefold()
    try:
        if suffix == ".docx":
            from docx import Document

            document = Document(str(path))
            return "\n".join(paragraph.text for paragraph in document.paragraphs).strip()
        if suffix == ".pdf":
            from pypdf import PdfReader

            raw = "\n".join(
                page.extract_text() or "" for page in PdfReader(str(path)).pages
            )
            return normalize_letter_text(raw)
        if suffix in {".txt", ".md", ".markdown", ".text"}:
            return unescape_newlines(
                path.read_text(encoding="utf-8", errors="ignore")
            ).strip()
    except Exception:
        logger.debug("Failed to parse cover letter %s", path.name, exc_info=True)
    try:
        return unescape_newlines(
            path.read_text(encoding="utf-8", errors="ignore")
        ).strip()
    except OSError:
        return ""
