"""Streaming adapters and artifact provenance. No business filtering here."""
import gzip
import hashlib
import json
import os
import re
import tempfile
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

REGISTRY = Path(__file__).with_name("sources.json")
RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
SKOS = "{http://www.w3.org/2004/02/skos/core#}"
LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def registry():
    return {s["id"]: s for s in json.loads(REGISTRY.read_text(encoding="utf-8"))}


def require_source(source_id, acknowledge=False):
    source = registry()[source_id]
    if source["review"] != "documented" and not acknowledge:
        raise ValueError("License review pending: consult source terms; use --acknowledge-terms only if permitted")
    return source


def digest(path, algorithm="sha256"):
    h = hashlib.new(algorithm)
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_upstream(path, source):
    if source.get("checksum"):
        algorithm, expected = source["checksum"].split(":", 1)
        if digest(path, algorithm) != expected:
            raise ValueError("Upstream checksum mismatch")


def download(source, root):
    if not source.get("url"):
        raise ValueError("No automated URL; obtain a snapshot from the source homepage")
    target = Path(root) / "raw" / source["id"] / source["version"] / source["filename"]
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        verify_upstream(target, source)
        return target
    fd, temporary = tempfile.mkstemp(dir=target.parent, suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f, urllib.request.urlopen(
            urllib.request.Request(source["url"], headers={"User-Agent": "corpus-assets/0.1"}), timeout=60
        ) as response:
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                f.write(chunk)
        verify_upstream(temporary, source)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return target


def open_input(path):
    return gzip.open(path, "rb") if str(path).endswith(".gz") else open(path, "rb")


def local(tag):
    return tag.rsplit("}", 1)[-1]


def normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def record(source, record_id, text, **extra):
    if not isinstance(text, str) or not text.strip() or not record_id:
        raise ValueError("Empty text or identifier")
    return dict(schema_version=1, source_id=source["id"], source_version=source["version"],
                kind=source["kind"], record_id=str(record_id), language="en",
                text=text, normalized_text=normalized(text), **extra)


def iter_titles(stream, source):
    for number, line in enumerate(stream, 1):
        try:
            obj = json.loads(line)
            title, video = obj.get("title"), obj.get("display_id")
            if not isinstance(title, str) or not title.strip() or not isinstance(video, str) or not video:
                yield None
                continue
            cat = obj.get("categories")
            labels = [cat] if isinstance(cat, str) and cat else (
                [x for x in cat if isinstance(x, str)] if isinstance(cat, list) else [])
            yield record(source, video, title, weak_labels=labels, channel_id=obj.get("channel_id"),
                         duration_seconds=obj.get("duration"), language_evidence="english-channel-selection")
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError(f"Invalid title JSONL at line {number}") from exc


def iter_wordnet(stream, source):
    # Retain sense-to-synset links; WordNet is not itself a domain taxonomy.
    stack = []
    for event, elem in ET.iterparse(stream, events=("start", "end")):
        if event == "start":
            stack.append(elem)
            continue
        tag = local(elem.tag)
        if tag == "LexicalEntry":
            lemma = next((x for x in elem if local(x.tag) == "Lemma"), None)
            if lemma is not None and lemma.get("writtenForm"):
                yield record(source, elem.get("id"), lemma.get("writtenForm"),
                             part_of_speech=lemma.get("partOfSpeech"),
                             synset_ids=[x.get("synset") for x in elem if local(x.tag) == "Sense" and x.get("synset")])
        elif tag == "Synset":
            definition = next((x.text for x in elem if local(x.tag) == "Definition" and x.text), None)
            if definition:
                yield record(source, elem.get("id"), definition, record_type="synset",
                             relations=[{"type": x.get("relType"), "target": x.get("target")}
                                        for x in elem if local(x.tag) == "SynsetRelation"])
        if tag in {"LexicalEntry", "Synset"}:
            if len(stack) > 1:
                stack[-2].remove(elem)
            elem.clear()
        stack.pop()


def iter_skos(stream, source):
    # RDF/XML with direct SKOS labels only; SKOS-XL-only inputs require conversion.
    stack = []
    for event, elem in ET.iterparse(stream, events=("start", "end")):
        if event == "start":
            stack.append(elem)
            continue
        if len(stack) == 2:
            uri = elem.get(RDF + "about")
            labels = [x.text for x in elem.findall(SKOS + "prefLabel")
                      if x.text and x.get(LANG, "").lower().split("-")[0] == "en"]
            if uri and labels:
                yield record(source, uri, labels[0],
                             aliases=[x.text for x in elem.findall(SKOS + "altLabel")
                                      if x.text and x.get(LANG, "").lower().split("-")[0] == "en"],
                             broader=[x.get(RDF + "resource") for x in elem.findall(SKOS + "broader")
                                      if x.get(RDF + "resource")])
            stack[-2].remove(elem)
            elem.clear()
        stack.pop()


from .adapters import iter_mesh, iter_esco, iter_onet, iter_wikidata, iter_wordlist, iter_seeds

ADAPTERS = {"wordnet": iter_wordnet, "youniverse": iter_titles, "skos": iter_skos,
            "mesh": iter_mesh, "esco": iter_esco, "onet": iter_onet,
            "wikidata": iter_wikidata, "wordlist": iter_wordlist, "seeds": iter_seeds}


@contextmanager
def atomic_output(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            yield stream
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def build(source, input_path, root, limit=None, snapshot=None):
    if source.get("adapter") not in ADAPTERS:
        raise ValueError("Adapter not implemented")
    if limit is not None and limit < 1:
        raise ValueError("Limit must be positive")
    source = dict(source)
    if source["version"] == "local-snapshot":
        if not snapshot or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", snapshot):
            raise ValueError("Provide --snapshot VERSION for manual sources")
        source["version"] = snapshot
    elif snapshot:
        raise ValueError("Snapshot override is only allowed for manual sources")
    verify_upstream(input_path, source)
    raw_sha = digest(input_path)
    suffix = "full" if limit is None else f"sample-{limit}"
    target = Path(root) / "processed" / source["id"] / source["version"] / raw_sha / (suffix + ".jsonl")
    counts = Counter()
    with open_input(input_path) as src, atomic_output(target) as out:
        for item in ADAPTERS[source["adapter"]](src, source):
            counts["read"] += 1
            if item is None:
                counts["skipped"] += 1
            else:
                out.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
                counts["written"] += 1
            if limit is not None and counts["read"] >= limit:
                break
        if not counts["written"]:
            raise ValueError("No valid records; check source format")
    manifest = dict(source=source, input_sha256=raw_sha, output_sha256=digest(target),
                    schema_version=1, limit=limit, counts=dict(counts))
    with atomic_output(str(target) + ".manifest.json") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)
    return target


def validate(path):
    path = Path(path)
    manifest = json.loads(Path(str(path) + ".manifest.json").read_text(encoding="utf-8"))
    if digest(path) != manifest["output_sha256"]:
        raise ValueError("Output checksum mismatch")
    total = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)
            for key in ("source_id", "source_version", "kind", "record_id", "language", "text", "normalized_text"):
                if not isinstance(item.get(key), str) or not item[key]:
                    raise ValueError(f"Invalid field: {key}")
            if item.get("schema_version") != 1 or item["normalized_text"] != normalized(item["text"]):
                raise ValueError("Schema mismatch")
            if item["source_id"] != manifest["source"]["id"] or item["source_version"] != manifest["source"]["version"]:
                raise ValueError("Source mismatch")
            total += 1
    if total != manifest["counts"]["written"] or not total:
        raise ValueError("Record count mismatch")
    return manifest
