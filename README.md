# Corpus Assets

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
SKOS-XL-only snapshots need conversion; live files are not yet tested. Other registered sources are candidates, not implemented adapters.

Use `CORPUS_ROOT=/path/to/storage` or `corpus --root /path/to/storage ...` to keep large assets off the repo disk.

## Data contract
Each JSONL record contains schema_version, source_id, source_version, kind, record_id, language, text, normalized_text. Source-specific fields preserve weak platform categories, synset references, relations or taxonomy parents. A sidecar manifest records the source/license, input and output SHA-256 and row counts. Content-addressed output paths separate snapshots and limited/full builds. Normalization is Unicode NFKC, casefold and whitespace normalization. IDs are not deduplicated yet. English selection for YouNiverse is channel-level, not proof of each title's language. No domain classification accuracy is asserted.

## Roadmap
- P0: registry, acquisition, streaming adapters, validation and fixture tests.
- P1: licensed domain vocabularies, canonical domain taxonomy and mapping.
- P2: entity, alias and activity resources.
- P3: representative category sampling, title term statistics and weak-label features.
- P4: searchable index and versioned exports.
- P5: integrate with data-cleaning-infra and validate on real title/QC samples.

Upstream terms may differ between data and code; retain attribution and review before commercial use or redistribution. No upstream datasets are included. Do not treat platform categories as business QC labels.
