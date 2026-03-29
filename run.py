import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

# Natural-language request: parser extracts recipient_email + brief for the SDR chain.
USER_MESSAGE = (
    "Send an email to geekyoswald@gmail.com about our AI tool for startups working toward SOC2 readiness."
)


async def main():
    from telegram_util import configure_complai_logging

    configure_complai_logging()
    from pipeline import run_sdr_pipeline

    result = await run_sdr_pipeline(USER_MESSAGE)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
