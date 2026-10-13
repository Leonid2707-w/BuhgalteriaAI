import logging
from pathlib import Path

from app.services.security import RedactingFilter


def configure_logging(level: str) -> None:
    Path("logs").mkdir(exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handlers: list[logging.Handler] = [
        logging.StreamHandler(),
        logging.FileHandler("logs/finance_bot.log", encoding="utf-8"),
    ]
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(RedactingFilter())
    logging.basicConfig(level=level.upper(), handlers=handlers, force=True)
