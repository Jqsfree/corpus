"""Bounded stratified sampling and title-only category statistics."""
import hashlib
import heapq
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from .core import atomic_output, digest, normalized, validate

TOKEN = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*", re.UNICODE)


def terms(text, max_n=2):
    tokens = TOKEN.findall(normalized(text))
    return { " ".join(tokens[i:i+n]) for n in range(1, max_n+1)
             for i in range(len(tokens)-n+1) }


def stratified(path, per_category=1000, seed="corpus-v1"):
    if per_category < 1 or per_category > 100000:
        raise ValueError("per-category must be in [1,100000]")
    heaps, seen, counts = defaultdict(list), defaultdict(set), Counter()
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            item = json.loads(line)
            if item["kind"] != "titles":
                raise ValueError("Expected normalized title corpus")
            key = item["record_id"]
            for label in set(item.get("weak_labels", [])) or {"__unlabeled__"}:
                counts[label] += 1
                heap = heaps[label]
                if key in seen[label]:
                    continue
                rank = int.from_bytes(hashlib.sha256((seed+"\0"+key).encode()).digest(), "big")
                entry = (-rank, key, item)
                if len(heap) < per_category:
                    heapq.heappush(heap, entry)
                    seen[label].add(key)
                elif entry[:2] > heap[0][:2]:
                    removed = heapq.heapreplace(heap, entry)
                    seen[label].remove(removed[1])
                    seen[label].add(key)
    return {label: [e[2] for e in sorted(heap, key=lambda e: (-e[0], e[1]))]
            for label, heap in sorted(heaps.items())}, counts


def title_features(path, output, per_category=1000, seed="corpus-v1", min_df=3, top=500):
    if min_df < 1 or top < 1:
        raise ValueError("min-df and top must be positive")
    manifest = validate(path)
    samples, counts = stratified(path, per_category, seed)
    if not samples:
        raise ValueError("No titles")
    category_df = {}
    for label, items in samples.items():
        counter = Counter()
        for item in items:
            counter.update(terms(item["text"]))
        category_df[label] = counter
    total = sum(map(len, samples.values()))
    pooled = Counter()
    for counter in category_df.values():
        pooled.update(counter)
    output = Path(output)
    with atomic_output(output) as stream:
        for label, counter in sorted(category_df.items()):
            size = len(samples[label])
            rest = total-size
            if label == "__unlabeled__" or not rest:
                continue
            scored = []
            for term, df in counter.items():
                if df < min_df:
                    continue
                other = pooled[term]-df
                # Smoothed log ratio of document prevalence, not calibrated probability.
                score = math.log((df+0.5)/(size+1)) - math.log((other+0.5)/(rest+1))
                if score > 0:
                    scored.append((score, df, term, other))
            for score, df, term, other in sorted(scored, key=lambda x:(-x[0],-x[1],x[2]))[:top]:
                stream.write(json.dumps(dict(category=label, term=term, df=df, sample_size=size,
                    other_df=other, other_sample_size=rest, log_prevalence_ratio=score,
                    label_type="platform_weak", source_id=manifest["source"]["id"]), sort_keys=True)+"\n")
    sample_file = Path(str(output)+".samples.jsonl")
    with atomic_output(sample_file) as stream:
        for label, items in samples.items():
            for item in items:
                stream.write(json.dumps({"category":label,"record_id":item["record_id"],"text":item["text"],"channel_id":item.get("channel_id")},ensure_ascii=False,sort_keys=True)+"\n")
    report = dict(schema_version=1, input_sha256=digest(path), output_sha256=digest(output),
                  sample_sha256=digest(sample_file), source=manifest["source"], seed=seed,
                  per_category=per_category, min_df=min_df, top=top,
                  observed_rows_by_category=dict(counts), sample_size_by_category={k:len(v) for k,v in samples.items()},
                  caveat="Category-stratified hash sample, not channel-balanced; platform labels overlap and are not QC truth.")
    with atomic_output(str(output)+".manifest.json") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
    return report
