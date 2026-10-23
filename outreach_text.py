"""Utilities for keeping generated outreach copy free of assistant UI text."""

from __future__ import annotations

import re


_UI_ONLY_LINE = re.compile(
    r"^(?:writing|thinking|working|searching|generating|chatgpt said|"
    r"copy(?: response)?|read aloud|good response|bad response|"
    r"regenerate(?: response)?|stop generating)\s*[.:…]*$",
    re.IGNORECASE,
)
_META_ONLY_LINE = re.compile(
    r"^(?:(?:sure|certainly|absolutely)[!,.:\s-]*)?"
    r"here(?:'s| is) (?:a|the|your) (?:concise |short |polished |professional )?"
    r"(?:draft|message|proposal|response|outreach message)(?: you can use)?\s*[:.!-]*$",
    re.IGNORECASE,
)
_IRRELEVANT_ASSISTANT_LINE = re.compile(
    r"^(?:as an ai(?: language model)?\b.*|i(?: am|'m) an ai(?: assistant)?\b.*|"
    r".*\b(?:written|generated|created) by (?:an? )?(?:ai|chatgpt)\b.*|"
    r"i hope (?:this|that) helps[.!]*|"
    r"(?:please )?let me know if you(?:'d| would) like\b.*|"
    r"feel free to (?:ask|request|adjust|edit)\b.*)\s*$",
    re.IGNORECASE,
)
_CONTENT_LABEL = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:assistant|ai response|response|draft|proposal|message)\s*:\s*",
    re.IGNORECASE,
)
_SUBJECT_LINE = re.compile(r"^\s*(?:\*{0,2})subject(?:\*{0,2})\s*:", re.IGNORECASE)


def clean_outreach_message(value) -> str:
    """Return only sendable message copy from an AI/browser response.

    Chat interfaces sometimes expose transient labels and action text through
    ``inner_text``. This removes those exact UI/meta lines without rewriting
    the customer's actual message.
    """

    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u200b", "").replace("\ufeff", "").strip()
    if not text:
        return ""

    lines = [line.rstrip() for line in text.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and re.fullmatch(r"```(?:text|markdown|md)?\s*", lines[0].strip(), re.I):
        lines.pop(0)
    if lines and re.fullmatch(r"```\s*", lines[-1].strip()):
        lines.pop()

    lines = [
        line for line in lines
        if not (
            line.strip()
            and (
                _UI_ONLY_LINE.fullmatch(line.strip())
                or _IRRELEVANT_ASSISTANT_LINE.fullmatch(line.strip())
            )
        )
    ]

    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and (
        _META_ONLY_LINE.fullmatch(lines[0].strip())
        or _SUBJECT_LINE.match(lines[0].strip())
    ):
        lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)

    if lines:
        # Keep text after labels such as "Proposal: Hello ...".
        lines[0] = _CONTENT_LABEL.sub("", lines[0], count=1)

    result = "\n".join(lines).strip()
    result = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", result)
    if len(result) >= 2 and result[0] == result[-1] and result[0] in {'"', "'"}:
        result = result[1:-1].strip()
    return result
