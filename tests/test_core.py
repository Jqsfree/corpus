import gzip
import json
import tempfile
import unittest
from pathlib import Path
from corpus_assets.core import build, validate, registry, require_source


class CorpusTests(unittest.TestCase):
    def test_wordnet(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "tiny.xml.gz"
            with gzip.open(p, "wb") as f:
                f.write(b'<LexicalResource><Lexicon><LexicalEntry id="e1"><Lemma writtenForm="Tractor" partOfSpeech="n"/><Sense synset="s1"/></LexicalEntry><Synset id="s1"><Definition>Farm machine</Definition><SynsetRelation relType="hypernym" target="s2"/></Synset></Lexicon></LexicalResource>')
            out = build(registry()["wordnet"], p, d)
            self.assertEqual(validate(out)["counts"]["written"], 2)
            self.assertEqual(json.loads(out.read_text().splitlines()[0])["synset_ids"], ["s1"])
            out.write_text("bad")
            with self.assertRaises(ValueError):
                validate(out)

    def test_titles_and_limit(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "tiny.jsonl.gz"
            with gzip.open(p, "wt") as f:
                f.write(json.dumps({"display_id":"abc","title":"Harvesting Wheat","categories":"Education"})+"\n")
                f.write(json.dumps({"display_id":"def","title":"second"})+"\n")
            source = dict(registry()["youniverse"])
            source.pop("checksum")  # synthetic fixture, never production source
            out = build(source, p, d, limit=1)
            item = json.loads(out.read_text())
            self.assertEqual(item["weak_labels"], ["Education"])
            self.assertEqual(item["normalized_text"], "harvesting wheat")
            self.assertEqual(validate(out)["counts"]["written"], 1)
            with self.assertRaises(ValueError):
                build(registry()["youniverse"], p, d)

    def test_skos(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/"tiny.rdf"
            p.write_text('<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:skos="http://www.w3.org/2004/02/skos/core#"><skos:Concept rdf:about="urn:a"><skos:prefLabel xml:lang="en">Agriculture</skos:prefLabel><skos:prefLabel xml:lang="fr">Agriculture</skos:prefLabel><skos:altLabel xml:lang="en">Farming</skos:altLabel></skos:Concept></rdf:RDF>')
            out = build(registry()["iptc"], p, d, snapshot="fixture")
            self.assertEqual(json.loads(out.read_text())["aliases"], ["Farming"])
            self.assertEqual(validate(out)["counts"]["written"], 1)

    def test_license_gate(self):
        with self.assertRaises(ValueError):
            require_source("youniverse")
        self.assertEqual(require_source("youniverse", True)["review"], "pending")
