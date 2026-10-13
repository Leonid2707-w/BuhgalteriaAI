from pathlib import Path

from openai import AsyncOpenAI


class OpenAITranscriber:
    def __init__(self, api_key: str, model: str, timeout: float) -> None:
        self.client = AsyncOpenAI(api_key=api_key, timeout=timeout, max_retries=2)
        self.model = model

    async def transcribe(self, path: Path) -> str:
        with path.open("rb") as audio:
            result = await self.client.audio.transcriptions.create(
                model=self.model,
                file=audio,
                language="ru",
                prompt=(
                    "Финансовая операция. Термины: 404 Team, BigBankClub, "
                    "Trading Bot, Скрудж, ChatGPT, DeepSeek, USDT, Binance."
                ),
            )
        return result.text.strip()
