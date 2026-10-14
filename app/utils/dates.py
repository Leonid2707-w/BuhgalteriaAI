from datetime import date, timedelta


def parse_relative_date(value: str, today: date) -> date | None:
    normalized = value.strip().lower()
    aliases = {
        "сегодня": today,
        "вчера": today - timedelta(days=1),
        "позавчера": today - timedelta(days=2),
        "завтра": today + timedelta(days=1),
    }
    if normalized in aliases:
        return aliases[normalized]
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None
