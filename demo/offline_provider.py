"""Deterministic offline provider used by examples and tests; never an LLM."""

import argparse
import hashlib
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="demo")
    parser.add_argument("--effort", default="medium")
    args = parser.parse_args()
    prompt = sys.stdin.read()
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
    print(f"DEMO PROVIDER (offline; deterministic; no model call)\n"
          f"model={args.model} effort={args.effort} prompt_sha256={digest}\n"
          f"prompt_chars={len(prompt)}")


if __name__ == "__main__":
    main()
