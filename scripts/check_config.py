import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_settings


def main() -> int:
    settings = load_settings()
    errors = settings.runtime_errors()
    if errors:
        print("Конфигурация требует настройки:")
        for error in errors:
            print(f"- {error}")
        return 2
    print("Конфигурация заполнена. Значения секретов не выводятся.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
