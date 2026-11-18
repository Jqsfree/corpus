import argparse
import json
import os
import sys
from pathlib import Path
from .core import registry, require_source, download, build, validate
from .analytics import title_features
from .index import index_build, search, export
from .matching import match_file


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
            p.add_argument("--input", type=Path)
            p.add_argument("--limit", type=int)
            p.add_argument("--snapshot")
            p.add_argument("--category", help="Upstream category for plain word lists")
    for name in ("validate", "stats"):
        p = commands.add_parser(name)
        p.add_argument("--input", required=True, type=Path)
    p = commands.add_parser("taxonomy")
    p = commands.add_parser("features")
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--per-category", type=int, default=1000)
    p.add_argument("--seed", default="corpus-v1")
    p.add_argument("--min-df", type=int, default=3)
    p.add_argument("--top", type=int, default=500)
    p = commands.add_parser("index")
    p.add_argument("--input", required=True, nargs="+", type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--include-titles", action="store_true")
    p = commands.add_parser("search")
    p.add_argument("--index", type=Path)
    p.add_argument("--term", required=True)
    p.add_argument("--domain")
    p.add_argument("--exact", action="store_true")
    p.add_argument("--mode", choices=["all","any","phrase","prefix","exact"], default="all")
    p.add_argument("--source")
    p.add_argument("--limit", type=int, default=20)
    p = commands.add_parser("export")
    p.add_argument("--index", type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--domain")
    p.add_argument("--source")
    p = commands.add_parser("match")
    p.add_argument("--index", type=Path)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--domain", action="append")
    p.add_argument("--source", action="append")
    p.add_argument("--backend", choices=["auto","hash","aho"],default="auto")
    p.add_argument("--min-chars", type=int, default=3)
    p.add_argument("--max-tokens",type=int,default=5)
    p.add_argument("--field",default="title")
    args = parser.parse_args(argv)
    default_index = args.root/"index"/"corpus.sqlite"
    try:
        if args.command == "sources":
            result = list(registry().values())
        elif args.command == "taxonomy":
            result = json.loads(Path(__file__).with_name("taxonomy.json").read_text())
        elif args.command in ("validate", "stats"):
            result = validate(args.input)
            if args.command == "stats":
                result = result["counts"]
        elif args.command == "features":
            result = title_features(args.input,args.output,args.per_category,args.seed,args.min_df,args.top)
        elif args.command == "index":
            result = index_build(args.input,args.output or default_index,args.include_titles)
        elif args.command == "search":
            result = search(args.index or default_index,args.term,args.limit,args.domain,args.exact,args.mode,args.source)
        elif args.command == "match":
            result = match_file(args.index or default_index,args.input,args.output,args.domain,args.source,args.backend,args.min_chars,args.max_tokens,args.field)
        elif args.command == "export":
            result = export(args.index or default_index,args.output,args.domain,args.source)
        else:
            source = require_source(args.source, args.acknowledge_terms)
            if args.command == "download":
                print(download(source,args.root))
                return 0
            if args.category:
                if source["adapter"] != "wordlist":
                    raise ValueError("--category applies only to wordlist")
                source = dict(source,upstream_category=args.category)
            input_path = args.input
            if input_path is None and args.source == "domain-seeds":
                input_path = Path(__file__).with_name("taxonomy.json")
            if input_path is None:
                raise ValueError("--input is required for external sources")
            print(build(source,input_path,args.root,args.limit,args.snapshot))
            return 0
        print(json.dumps(result,indent=2,ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"corpus: {exc}",file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
