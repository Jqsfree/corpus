import json
import tempfile
import unittest
from pathlib import Path
from corpus_assets.core import build, registry
from corpus_assets.index import index_build,search
from corpus_assets.matching import load_matcher,match_file,Matcher


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        raw=self.root/"seeds.json"
        raw.write_text(json.dumps({"domains":[{"id":"agriculture","terms":["tractor","tractor repair","harvest wheat","wheat","café farming"]},{"id":"transport","terms":["engine repair","tractor"]}]}))
        self.artifact=build(registry()["domain-seeds"],raw,self.root)
        self.db=self.root/"index.sqlite"
        index_build([self.artifact],self.db)

    def test_search_modes(self):
        self.assertEqual(search(self.db,"tractor repair")[0]["text"],"tractor repair")
        self.assertEqual(search(self.db,"repair tractor",mode="phrase"),[])
        self.assertEqual(search(self.db,"tractor repair",mode="phrase")[0]["text"],"tractor repair")
        self.assertTrue(search(self.db,"engine nonexistent",mode="any"))
        self.assertTrue(search(self.db,"tractor rep",mode="prefix"))
        self.assertFalse(search(self.db,"engine nonexistent"))
        self.assertFalse(search(self.db,"tractor",source="mesh"))
        self.assertTrue(search(self.db,"tractor",domain="agriculture",mode="exact"))

    def test_match_word_boundaries_and_domains(self):
        matcher,_=load_matcher(self.db,["agriculture"],backend="hash")
        result=matcher.match("TRACTOR-repair and wheat")
        self.assertEqual(result["domain_hit_counts"],{"agriculture":3})
        self.assertEqual(matcher.match("contractor")["matches"],[])
        self.assertTrue(matcher.match("café farming")["matches"])
        self.assertFalse(matcher.match("engine repair")["matches"])
        both,_=load_matcher(self.db,backend="hash")
        self.assertEqual(both.match("tractor")["domain_hit_counts"],{"agriculture":1,"transport":1})
        inp=self.root/"titles.jsonl"
        inp.write_text('{"video_id":"1","title":"tractor repair"}\n{"video_id":"2","title":"unknown"}\n')
        out=self.root/"hits.jsonl"
        report=match_file(self.db,inp,out,backend="hash")
        self.assertEqual((report["rows"],report["matched_rows"]),(2,1))
        self.assertEqual(json.loads(out.read_text().splitlines()[1])["corpus_match"]["matches"],[])
        with self.assertRaises(ValueError):
            match_file(self.db,inp,inp)

    def test_backend_parity(self):
        base,_=load_matcher(self.db,backend="hash")
        try:
            import ahocorasick
        except ImportError:
            self.skipTest("Optional accelerator not installed")
        fast,_=load_matcher(self.db,backend="aho")
        for title in ["tractor repair tractor","harvest wheat","contractor","café farming","TRACTOR-repair","","engine repair"]:
            self.assertEqual(base.match(title),fast.match(title))
