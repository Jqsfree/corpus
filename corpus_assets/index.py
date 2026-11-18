"""Local SQLite artifact index; evidence lookup, not automatic classification."""
import json
import os
import re
import sqlite3
import tempfile
from pathlib import Path
from .core import atomic_output, digest, normalized, validate

SCHEMA = """
CREATE TABLE records(id INTEGER PRIMARY KEY, source TEXT NOT NULL, version TEXT NOT NULL,
  record_id TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, payload TEXT NOT NULL,
  UNIQUE(source,version,record_id));
CREATE TABLE terms(record INTEGER NOT NULL REFERENCES records(id), term TEXT NOT NULL,
  PRIMARY KEY(record,term));
CREATE INDEX terms_lookup ON terms(term);
CREATE TABLE domains(record INTEGER NOT NULL REFERENCES records(id), domain TEXT NOT NULL,
  PRIMARY KEY(record,domain));
CREATE INDEX domains_lookup ON domains(domain);
CREATE VIRTUAL TABLE search USING fts5(text, aliases, tokenize='unicode61');
CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def index_build(paths, output, include_titles=False):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=output.parent, suffix=".sqlite.part")
    os.close(fd)
    metadata = []
    written = duplicates = 0
    try:
        with sqlite3.connect(name) as db:
            db.executescript(SCHEMA)
            for path in paths:
                manifest = validate(path)
                kind = manifest["source"]["kind"]
                if kind == "titles" and not include_titles:
                    raise ValueError("Raw titles are excluded by default; use --include-titles explicitly")
                metadata.append(manifest)
                with Path(path).open(encoding="utf-8") as stream:
                    for line in stream:
                        item = json.loads(line)
                        payload = json.dumps(item, ensure_ascii=False, sort_keys=True)
                        args = (item["source_id"],item["source_version"],item["record_id"],item["kind"],item["text"],payload)
                        cursor = db.execute("INSERT OR IGNORE INTO records(source,version,record_id,kind,text,payload) VALUES (?,?,?,?,?,?)",args)
                        if not cursor.rowcount:
                            old = db.execute("SELECT payload FROM records WHERE source=? AND version=? AND record_id=?",args[:3]).fetchone()[0]
                            if old != payload:
                                raise ValueError("Conflicting record identity: "+str(args[:3]))
                            duplicates += 1
                            continue
                        key = cursor.lastrowid
                        aliases = [v for v in item.get("aliases", []) if isinstance(v,str)]
                        db.executemany("INSERT OR IGNORE INTO terms VALUES (?,?)",[(key,v) for v in sorted({normalized(v) for v in [item["text"],*aliases] if normalized(v)})])
                        db.executemany("INSERT OR IGNORE INTO domains VALUES (?,?)",[(key,v) for v in item.get("domain_hints",[])])
                        db.execute("INSERT INTO search(rowid,text,aliases) VALUES (?,?,?)",(key,item["text"]," ".join(aliases)))
                        written += 1
                        if written % 10000 == 0:
                            db.commit()
            if not written:
                raise ValueError("Empty index")
            report = dict(schema_version=1, records=written, duplicate_records=duplicates, inputs=metadata)
            db.execute("INSERT INTO metadata VALUES (?,?)",("manifest",json.dumps(report,sort_keys=True)))
        os.replace(name,output)
        return report
    finally:
        Path(name).unlink(missing_ok=True)


def connect(path):
    return sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro", uri=True)


def search(path, term, limit=20, domain=None, exact=False):
    if not 1 <= limit <= 1000 or not normalized(term):
        raise ValueError("Nonempty term and limit 1..1000 required")
    where = " AND EXISTS(SELECT 1 FROM domains d WHERE d.record=r.id AND d.domain=?)" if domain else ""
    if exact:
        sql = "SELECT r.payload FROM terms t JOIN records r ON r.id=t.record WHERE t.term=?"+where+" ORDER BY r.id LIMIT ?"
        value = normalized(term)
    else:
        words = re.findall(r"[^\W_]+", term, re.UNICODE)
        if not words:
            raise ValueError("No searchable tokens")
        value = " AND ".join('"'+w+'"' for w in words)
        sql = "SELECT r.payload FROM search JOIN records r ON r.id=search.rowid WHERE search MATCH ?"+where+" ORDER BY bm25(search),r.id LIMIT ?"
    with connect(path) as db:
        return [json.loads(row[0]) for row in db.execute(sql,[value]+([domain] if domain else [])+[limit])]


def export(path, output, domain=None, source=None):
    if Path(path).resolve() == Path(output).resolve():
        raise ValueError("Output may not overwrite index")
    filters, args = [], []
    if domain:
        filters.append("EXISTS(SELECT 1 FROM domains d WHERE d.record=r.id AND d.domain=?)")
        args.append(domain)
    if source:
        filters.append("r.source=?")
        args.append(source)
    query = "SELECT payload FROM records r"+(" WHERE "+" AND ".join(filters) if filters else "")+" ORDER BY source,version,record_id"
    count = 0
    with connect(path) as db, atomic_output(output) as stream:
        meta = json.loads(db.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])
        for (row,) in db.execute(query,args):
            stream.write(row+"\n")
            count += 1
    report = dict(index_manifest=meta, index_sha256=digest(path), output_sha256=digest(output),
                  filters=dict(domain=domain,source=source), count=count, schema_version=1)
    with atomic_output(str(output)+".manifest.json") as stream:
        json.dump(report,stream,indent=2,sort_keys=True)
    return report
