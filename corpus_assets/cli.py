import argparse
import json
import os
import sys
from pathlib import Path
from .core import registry, require_source, download, build, validate


def main(argv=None):
    parser = argparse.ArgumentParser(prog="corpus")
    parser.add_argument("--root", type=Path, default=Path(os.environ.get("CORPUS_ROOT", "data")))
    commands = parser.add_subparsers(dest="command", required=True)
    sources = commands.add_parser("sources")
    sources.add_argument("action", choices=["list"])
    for name in ("download", "build"):
        p = commands.add_parser(name)
        p.add_argument("--source", required=True, choices=registry())
        p.add_argument("--acknowledge-terms", action="store_true")
        if name == "build":
            p.add_argument("--input", required=True, type=Path)
            p.add_argument("--limit", type=int)
            p.add_argument("--snapshot")
    for name in ("validate", "stats"):
        p = commands.add_parser(name)
        p.add_argument("--input", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "sources":
            print(json.dumps(list(registry().values()), indent=2, ensure_ascii=False))
        elif args.command in ("validate", "stats"):
            result = validate(args.input)
            print(json.dumps(result if args.command == "validate" else result["counts"], indent=2))
        else:
            source = require_source(args.source, args.acknowledge_terms)
            if args.command == "download":
                print(download(source, args.root))
            else:
                print(build(source, args.input, args.root, args.limit, args.snapshot))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"corpus: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
