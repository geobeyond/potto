#!/usr/bin/env python3
"""Polls a URL until it responds successfully or a timeout is reached."""

import argparse
import sys
import time
import urllib.error
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--max-attempts", type=int, default=30)
    args = parser.parse_args()

    for attempt in range(args.max_attempts):
        try:
            with urllib.request.urlopen(args.url) as response:
                if response.status == 200:
                    print(f"Server is ready at {args.url} (after {attempt}s)")
                    return 0
        except (urllib.error.URLError, ConnectionError):
            pass
        time.sleep(1)

    print(
        f"Server did not become ready at {args.url} after {args.max_attempts}s",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
