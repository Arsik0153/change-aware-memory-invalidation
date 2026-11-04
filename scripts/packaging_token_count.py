#!/usr/bin/env python3
"""Offline named-tokenizer estimate. No registry lookup, network or subject execution."""
from __future__ import annotations

import argparse
import base64
from importlib.metadata import version
import json
from pathlib import Path
import sys


def count(config_path, vocab_path, text):
    config = json.loads(config_path.read_text())
    if (config["package"] != "tiktoken" or config["package_version"] != "0.12.0"
            or version("tiktoken") != config["package_version"] or config["encoding_name"] != "o200k_base"):
        raise ValueError("named offline tokenizer identity mismatch")
    from tiktoken import Encoding
    ranks = {}
    for line in vocab_path.read_bytes().splitlines():
        token, rank = line.split()
        decoded = base64.b64decode(token, validate=True)
        if decoded in ranks:
            raise ValueError("duplicate local vocabulary token")
        ranks[decoded] = int(rank)
    encoding = Encoding(config["encoding_name"], pat_str=config["pat_str"], mergeable_ranks=ranks,
                        special_tokens=config["special_tokens"])
    return {"encoding": config["encoding_name"], "package_version": config["package_version"],
            "estimated_tokens": len(encoding.encode_ordinary(text)), "utf8_bytes": len(text.encode("utf-8")),
            "budget_role": "sealed research envelope estimate only; excludes uncontrolled harness/system/tool metadata; not actual model context or billing"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--vocab", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(count(args.config, args.vocab, sys.stdin.buffer.read().decode("utf-8", "strict"))))


if __name__ == "__main__":
    main()
