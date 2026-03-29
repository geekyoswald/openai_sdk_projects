import asyncio
import json

from dotenv import load_dotenv

load_dotenv(override=True)

# Natural-language request: parser extracts recipient_email + brief for the SDR chain.
USER_MESSAGE = (
    "Send an email to geekyoswald@gmail.com about our AI tool for startups working toward SOC2 readiness."
)


async def main():
    from pipeline import run_sdr_pipeline

    result = await run_sdr_pipeline(USER_MESSAGE)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
