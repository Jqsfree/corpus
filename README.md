# Corpus Assets (0.4.1)

Independent data assets for English YouTube title domain recognition and keyword expansion. The cleaning engine stays separate. Git stores code and manifests; raw data and generated assets stay local.

## Install
```bash
git clone https://github.com/Jqsfree/corpus.git
cd corpus
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
corpus sources list
```

## P0: actual ingestion
```bash
corpus download --source wordnet
corpus build --source wordnet --input data/raw/wordnet/2024/english-wordnet-2024.xml.gz
```
Build prints the generated JSONL path. Pass that exact path to `corpus validate --input PATH` and `corpus stats --input PATH`.

YouNiverse metadata is 13.6 GB compressed. Its use terms are pending review; do not download or process it unless the terms permit your intended use. After review:
```bash
corpus download --source youniverse --acknowledge-terms
corpus build --source youniverse --acknowledge-terms --input data/raw/youniverse/4650046/yt_metadata_en.jsonl.gz --limit 10000
```
The limit is a prefix smoke test, not representative sampling. Full build omits it. The source checksum is verified even for limited builds. No comment data is ingested.

IPTC and AGROVOC support manually downloaded RDF/XML snapshots with direct English SKOS labels:
```bash
corpus build --source iptc --input /path/to/mediatopic.rdf --snapshot YOUR_VERSION
```
SKOS-XL-only snapshots need conversion; live files are not yet tested. MeSH, ESCO, O*NET, selected Wikidata JSONL and categorized wordlist adapters are now available as manual imports; funNLP and DomainWordsDict remain registered reference sources.

Use `CORPUS_ROOT=/path/to/storage` or `corpus --root /path/to/storage ...` to keep large assets off the repo disk.

## Data contract
Each JSONL record contains schema_version, source_id, source_version, kind, record_id, language, text, normalized_text. Source-specific fields preserve weak platform categories, synset references, relations or taxonomy parents. A sidecar manifest records the source/license, input and output SHA-256 and row counts. Content-addressed output paths separate snapshots and limited/full builds. Normalization is Unicode NFKC, casefold and whitespace normalization. IDs are not deduplicated yet. English selection for YouNiverse is channel-level, not proof of each title's language. No domain classification accuracy is asserted.

## P1–P4: local workflow

```bash
corpus taxonomy
SEEDS=$(corpus build --source domain-seeds)
corpus validate --input "$SEEDS"
corpus index --input "$SEEDS"
corpus search --term tractor --exact
corpus export --domain agriculture --output data/exports/agriculture.jsonl
```

The bundled taxonomy is an initial English seed vocabulary, not a trained classifier or a comprehensive ontology. For external sources manually download and unpack the named format from the registry homepage, review the terms, and pin the actual upstream snapshot:

```bash
corpus build --source mesh --snapshot 2026 --input /path/to/desc2026.xml --acknowledge-terms
corpus build --source esco --snapshot 1.2.0 --input /path/to/skills_en.csv --acknowledge-terms
corpus build --source onet --snapshot 31.0 --input "/path/to/Task Statements.txt" --acknowledge-terms
corpus build --source wikidata --snapshot YOUR_DATE --input /path/to/selected-entities.jsonl
corpus build --source categorized-english-words --snapshot YOUR_COMMIT --category engineering --input /path/to/engineering.txt --acknowledge-terms
```

MeSH input is descriptor XML; ESCO English CSV occupations or skills; O*NET tab-delimited occupation or task records; Wikidata input is selected native entity objects as JSONL, not the massive full dump; categorized wordlist is one UTF-8 term per line. License acknowledgements mean you have reviewed permission; they are not license grants. AGROVOC direct-SKOS RDF/XML only; SKOS-XL conversion is still pending. Seed terms and MeSH carry explicit hints. At index time, selected IPTC concept IDs and their descendants map through the project taxonomy (mapping hash recorded); ambiguous/unmapped concepts and other upstream labels are not forcibly mapped. Search/export show these as index_domain_hints.

After YouNiverse full normalization, calculate title-only weak category features:
```bash
corpus features --input PATH_TO_FULL_TITLES_JSONL --output data/features/category_terms.jsonl --per-category 5000 --min-df 5 --top 1000
```
Sampling is deterministic bottom-k by video ID per category (bounded memory), with observed counts, sample provenance, unigram/bigram document frequency and smoothed log prevalence ratio against other categories. These are weak signals, not probabilities or verified domain labels. A prefix-limited input will bias the results. Features are separate weak-evidence artifacts and are not implicitly promoted into lexicons. When nonempty, the command also produces a normalized *.indexable.jsonl artifact with provenance so it can be indexed alongside the lexicons.

Build an index from explicit normalized JSONL paths (not raw files or feature outputs):
```bash
corpus index --input PATH_TO_SEEDS_JSONL PATH_TO_WORDNET_JSONL PATH_TO_MESH_JSONL
corpus search --term "hydraulic pump" --limit 20
corpus export --source mesh --output data/exports/mesh.jsonl
```
SQLite FTS5 supports token/alias search and exact normalized lookups; domain filters apply only to explicit canonical hints. Source and version are retained; identical identities deduplicate, conflicting records fail. Raw title indexes are opt-in with --include-titles (very large disk footprint). JSONL exports carry an index provenance sidecar. The index is rebuilt atomically from listed inputs; omitted inputs are not retained. Use shell quoting for paths containing spaces. No clearing or deletion of raw data.

## Retrieval and batch matching

Two different operations need different algorithms:

* Interactive lookup: SQLite exact indexed lookup and FTS5 inverted index + BM25. Exact full term/alias hits precede BM25; preferred text has weight 2, aliases 1. These weights are initial heuristics, not measured optima.
* Batch title matching: construct a domain-aware dictionary once and stream JSONL titles. Default auto chooses optional C-backed Aho-Corasick if installed; otherwise use bounded token n-gram hash lookup. Both emit the same evidence. No per-title SQL query, model call or automatic rejection.

```bash
pip install -e '.[fast]'
corpus search --term "tractor repair" --mode phrase
corpus search --term "tractor engine" --mode any --domain agriculture
corpus search --term "tract" --mode prefix
corpus search --term "tractor" --mode exact
corpus match --input titles.jsonl --output data/matched.jsonl --domain agriculture --backend auto
```

Only canonical-domain lexicon/taxonomy/entity/activity records enter the matcher. Unknown domains, weak platform category features, and raw titles are deliberately excluded. JSONL input requires a title field (override with --field); every input row survives, with corpus_match evidence and domain hit counts. Casefold/NFKC and punctuation-separated word tokens prevent substring false matches (tractor vs contractor). Punctuation-sensitive terms and short acronyms need separate handling; default minimum 3 nonspace characters and max 5 tokens. No stemming or embedding expansion is applied. Overlapping and multi-domain hits remain observable, and scores are not probabilities. Large dictionaries should be scoped with repeatable --domain/--source. Memory/throughput on actual data remains unmeasured. Existing index format remains compatible.

References: [SQLite FTS5](https://www.sqlite.org/fts5.html), [pyahocorasick](https://pyahocorasick.readthedocs.io/en/latest/).

## Roadmap
- P0: registry, acquisition, streaming adapters, validation and fixture tests.
- P1: seed taxonomy and manual domain resource adapters; selected IPTC hierarchy mappings; no exhaustive mapping.
- P2: selected entity, alias and activity adapters; no full dump materialized.
- P3: deterministic category sampling and weak-label title statistics; real corpus run pending.
- P4: SQLite FTS5 and provenance exports; performance at scale pending.
- P5: integrate with data-cleaning-infra and validate on real title/QC samples.

Upstream terms may differ between data and code; retain attribution and review before commercial use or redistribution. No upstream datasets are included. Do not treat platform categories as business QC labels.
