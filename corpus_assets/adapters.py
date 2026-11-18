"""Source-specific parsers. Import core functions lazily to avoid cycles."""
import csv
import hashlib
import io
import json
import xml.etree.ElementTree as ET


def iter_mesh(stream, source):
    from .core import record
    stack = []
    for event, el in ET.iterparse(stream, events=("start", "end")):
        if event == "start":
            stack.append(el)
            continue
        if el.tag == "DescriptorRecord":
            key, name = el.findtext("DescriptorUI"), el.findtext("DescriptorName/String")
            if key and name:
                aliases = sorted({t.text for t in el.findall("./ConceptList/Concept/TermList/Term/String") if t.text and t.text != name})
                yield record(source, key, name, aliases=aliases, domain_hints=["healthcare"],
                             tree_numbers=[t.text for t in el.findall("./TreeNumberList/TreeNumber") if t.text])
            if len(stack) > 1:
                stack[-2].remove(el)
            el.clear()
        stack.pop()


def rows(stream, delimiter=","):
    return csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig", newline=""), delimiter=delimiter)


def iter_esco(stream, source):
    from .core import record
    reader = rows(stream)
    if not {"conceptUri","preferredLabel"}.issubset(reader.fieldnames or []):
        raise ValueError("Expected English ESCO occupations or skills CSV: conceptUri, preferredLabel")
    for row in reader:
        key, name = row.get("conceptUri"), row.get("preferredLabel")
        if not key or not name:
            yield None
            continue
        aliases = [v.strip() for v in (row.get("altLabels") or "").splitlines() if v.strip()]
        yield record(source, key, name, aliases=aliases, description=row.get("description"),
                     record_type=row.get("conceptType"), isco_group=row.get("iscoGroup"))


def iter_onet(stream, source):
    from .core import record
    reader = rows(stream, "\t")
    cols = set(reader.fieldnames or [])
    if not {"O*NET-SOC Code","Task ID","Task"}.issubset(cols) and not {"O*NET-SOC Code","Title"}.issubset(cols):
        raise ValueError("Expected O*NET tab-delimited Task Statements.txt or Occupation Data.txt")
    for row in reader:
        code = row.get("O*NET-SOC Code")
        if not code:
            yield None
            continue
        if "Task" in cols:
            key, name, typ = row.get("Task ID"), row.get("Task"), "task"
            key = f"task:{code}:{key}" if key else None
        else:
            key, name, typ = "occupation:"+code, row.get("Title"), "occupation"
        if key and name:
            yield record(source, key, name, occupation_code=code, record_type=typ)
        else:
            yield None


def iter_wikidata(stream, source):
    from .core import record
    # Accept selected native entity objects, one JSON object per line, not the full JSON array dump.
    for n, line in enumerate(stream, 1):
        try:
            item = json.loads(line)
            key = item["id"]
            name = item.get("labels", {}).get("en", {}).get("value")
            aliases = [v["value"] for v in item.get("aliases", {}).get("en", []) if "value" in v]
            desc = item.get("descriptions", {}).get("en", {}).get("value")
            if name:
                yield record(source, key, name, aliases=aliases, description=desc)
            else:
                yield None
        except (ValueError, KeyError, AttributeError, TypeError) as exc:
            raise ValueError(f"Invalid Wikidata entity JSONL at line {n}") from exc


def iter_wordlist(stream, source):
    from .core import record, normalized
    # One UTF-8 file per upstream category; category must be supplied in source metadata.
    category = source.get("upstream_category")
    if not category:
        raise ValueError("Provide --category for wordlist import")
    for line in io.TextIOWrapper(stream, encoding="utf-8-sig"):
        value = line.strip()
        if not value:
            yield None
            continue
        key = hashlib.sha256((category+"\0"+normalized(value)).encode()).hexdigest()
        yield record(source, key, value, weak_labels=[category])


def iter_seeds(stream, source):
    from .core import record
    obj = json.load(stream)
    for domain in obj["domains"]:
        for term in domain["terms"]:
            key = hashlib.sha256((domain["id"]+"\0"+term).encode()).hexdigest()
            yield record(source, key, term, domain_hints=[domain["id"]], record_type="seed_term")
