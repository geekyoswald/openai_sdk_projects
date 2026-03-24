import asyncio
import json

from dotenv import load_dotenv

load_dotenv(override=True)

# Edit this string if you want a different prompt later.
BRIEF = "Send out a cold sales email addressed to Dear CEO from Head of Business Development"


async def main():
    from pipeline import run_sdr_pipeline

    result = await run_sdr_pipeline(BRIEF)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
