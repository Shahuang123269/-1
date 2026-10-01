"""Day 1: a minimal command-line program that calls the Responses API.

Run: python main.py "Explain what an AI agent is in one sentence."
"""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI, RateLimitError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ask an OpenAI model one question.")
    parser.add_argument("prompt", help="The question or task to send to the model.")
    return parser.parse_args()


def main() -> int:
    load_dotenv()
    args = parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        print(
            "OPENAI_API_KEY is missing. Copy .env.example to .env and add your key.",
            file=sys.stderr,
        )
        return 2

    model = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
    client = OpenAI()

    try:
        response = client.responses.create(model=model, input=args.prompt)
    except AuthenticationError:
        print("Authentication failed. Check OPENAI_API_KEY in .env.", file=sys.stderr)
        return 3
    except RateLimitError:
        print("Request was rate-limited. Wait briefly, then try again.", file=sys.stderr)
        return 4
    except APIConnectionError:
        print("Could not reach the API. Check your network connection.", file=sys.stderr)
        return 5
    except APIStatusError as error:
        print(f"API returned status {error.status_code}: {error.message}", file=sys.stderr)
        return 6

    print(response.output_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

