import re

CARD_LIKE = re.compile(r"(?<!\d)(?:\d[\s-]?){11,18}\d(?!\d)")
SECRET_ASSIGNMENT = re.compile(
    r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*\S+"
)


def redact_sensitive(value: str) -> str:
    value = CARD_LIKE.sub("[СКРЫТО]", value)
    return SECRET_ASSIGNMENT.sub(r"\1=[СКРЫТО]", value)


def sanitize_for_ai(value: str) -> str:
    return redact_sensitive(value)
