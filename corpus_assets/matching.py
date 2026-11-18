"""Title-to-lexicon multi-pattern matching; no automatic QC decisions."""
import json
import re
from collections import defaultdict
from pathlib import Path
from .core import atomic_output, digest, normalized
from .index import connect

TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def token_key(text):
    return " ".join(TOKEN.findall(normalized(text)))


class Matcher:
    def __init__(self, entries, backend="auto", max_tokens=5):
        if backend not in {"auto","hash","aho"}:
            raise ValueError("Unknown backend")
        self.entries = entries
        self.lengths = sorted({len(k.split()) for k in entries})
        if not 1 <= max_tokens <= 20:
            raise ValueError("max-tokens must be 1..20")
        self.backend = "hash"
        self.automaton = None
        if backend != "hash":
            try:
                import ahocorasick
            except ImportError:
                if backend == "aho":
                    raise ValueError("Install corpus-assets[fast] for Aho-Corasick") from None
            else:
                self.backend = "aho"
                if entries:
                    auto = ahocorasick.Automaton()
                    for term in sorted(entries):
                        auto.add_word(" "+term+" ",term)
                    auto.make_automaton()
                    self.automaton = auto

    def match(self, title):
        key = token_key(title)
        hits = set()
        if self.backend == "aho":
            if self.automaton:
                hits.update(term for _,term in self.automaton.iter(" "+key+" "))
        else:
            tokens = key.split()
            for n in self.lengths:
                for i in range(len(tokens)-n+1):
                    part = " ".join(tokens[i:i+n])
                    if part in self.entries:
                        hits.add(part)
        evidence = [{"term":term,"references":self.entries[term]} for term in sorted(hits)]
        by_domain = defaultdict(set)
        for item in evidence:
            for ref in item["references"]:
                by_domain[ref["domain"]].add(item["term"])
        return {"matches":evidence,
                "domain_hit_counts":{d:len(ts) for d,ts in sorted(by_domain.items())}}


def load_matcher(path, domains=None, sources=None, backend="auto", min_chars=3, max_tokens=5):
    if min_chars < 1 or not 1 <= max_tokens <= 20:
        raise ValueError("Invalid term limits")
    where = ["r.kind IN ('lexicon','taxonomy','entities','activities')"]
    parameters = []
    for values, column in ((domains,"d.domain"),(sources,"r.source")):
        if values:
            where.append(column+" IN ("+",".join("?" for _ in values)+")")
            parameters.extend(values)
    query = ("SELECT t.term,d.domain,r.source,r.version,r.record_id FROM terms t "
             "JOIN domains d ON d.record=t.record JOIN records r ON r.id=t.record WHERE "
             +" AND ".join(where)+" ORDER BY t.term,d.domain,r.source,r.version,r.record_id")
    entries = defaultdict(list)
    # Only terms with explicit canonical domain hints are eligible. Generic unlabeled
    # vocabulary, raw title records and weak-category features are not silently used.
    with connect(path) as db:
        manifest = json.loads(db.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])
        for term,domain,source,version,record_id in db.execute(query,parameters):
            key = token_key(term)
            if len(key.replace(" ","")) < min_chars or len(key.split()) > max_tokens:
                continue
            ref = dict(domain=domain,source=source,version=version,record_id=record_id,original_term=term)
            entries[key].append(ref)
    return Matcher(dict(entries),backend,max_tokens),manifest


def match_file(index_path, input_path, output_path, domains=None, sources=None,
               backend="auto", min_chars=3, max_tokens=5, field="title"):
    index_path,input_path,output_path=map(Path,(index_path,input_path,output_path))
    sidecar=Path(str(output_path)+".manifest.json")
    if {index_path.resolve(),input_path.resolve()} & {output_path.resolve(),sidecar.resolve()}:
        raise ValueError("Outputs must not overwrite inputs")
    matcher,manifest=load_matcher(index_path,domains,sources,backend,min_chars,max_tokens)
    total=matched=0
    with input_path.open(encoding="utf-8") as src, atomic_output(output_path) as out:
        for number,line in enumerate(src,1):
            obj=json.loads(line)
            if not isinstance(obj,dict) or not isinstance(obj.get(field),str):
                raise ValueError(f"Expected string field {field!r} at line {number}")
            if "corpus_match" in obj:
                raise ValueError(f"Existing corpus_match at line {number}")
            result=matcher.match(obj[field])
            total+=1
            matched+=bool(result["matches"])
            out.write(json.dumps(dict(obj,corpus_match=result),ensure_ascii=False,sort_keys=True)+"\n")
    report=dict(schema_version=1,backend=matcher.backend,distinct_patterns=len(matcher.entries),
                input_sha256=digest(input_path),index_sha256=digest(index_path),
                output_sha256=digest(output_path),index_manifest=manifest,
                domains=domains,sources=sources,min_chars=min_chars,max_tokens=max_tokens,
                title_field=field,rows=total,matched_rows=matched,
                caveat="Lexical evidence only; misses and multiple matches are not QC decisions.")
    with atomic_output(sidecar) as stream:
        json.dump(report,stream,indent=2,sort_keys=True)
    return report
