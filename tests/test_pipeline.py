import json
import tempfile
import unittest
from pathlib import Path
from corpus_assets.core import build,validate,registry
from corpus_assets.analytics import title_features
from corpus_assets.index import index_build,search,export

class PipelineTests(unittest.TestCase):
    def test_seed_index_export(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            taxonomy=Path(__file__).parents[1]/"corpus_assets"/"taxonomy.json"
            seeds=build(registry()["domain-seeds"],taxonomy,root)
            self.assertGreater(validate(seeds)["counts"]["written"],100)
            db=root/"index.sqlite"
            report=index_build([seeds,seeds],db)
            self.assertEqual(report["records"],report["duplicate_records"])
            self.assertEqual(search(db,"tractor",domain="agriculture",exact=True)[0]["text"],"tractor")
            self.assertEqual(search(db,"tract or"),[])
            out=root/"agriculture.jsonl"
            self.assertGreater(export(db,out,domain="agriculture")["count"],0)
            self.assertTrue(all("agriculture" in json.loads(x)["domain_hints"] for x in out.read_text().splitlines()))

    def test_mesh_esco_onet_entity(self):
        inputs={
            "mesh":('<DescriptorRecordSet><DescriptorRecord><DescriptorUI>D1</DescriptorUI><DescriptorName><String>Heart</String></DescriptorName><ConceptList><Concept><TermList><Term><String>Cardiac organ</String></Term></TermList></Concept></ConceptList></DescriptorRecord></DescriptorRecordSet>',"Heart"),
            "esco":('conceptUri,preferredLabel,altLabels\nurn:1,Carpenter,Joiner\n',"Carpenter"),
            "onet":('O*NET-SOC Code\tTask ID\tTask\n1\t2\tOperate machinery\n',"Operate machinery"),
            "wikidata":(json.dumps({"id":"Q1","labels":{"en":{"value":"Tractor"}},"aliases":{"en":[{"value":"Farm tractor"}]}})+"\n","Tractor"),
            "categorized-english-words":("hydraulics\n","hydraulics")
        }
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            results=[]
            for source_id,(data,want) in inputs.items():
                path=root/(source_id+".txt")
                path.write_text(data)
                src=registry()[source_id]
                if source_id=="categorized-english-words":
                    src=dict(src,upstream_category="engineering")
                out=build(src,path,root,snapshot="fixture")
                self.assertEqual(json.loads(out.read_text())["text"],want)
                validate(out)
                results.append(out)
            db=root/"db.sqlite"
            index_build(results,db)
            self.assertEqual(search(db,"Cardiac organ",exact=True)[0]["text"],"Heart")
            self.assertEqual(search(db,"farm tractor")[0]["text"],"Tractor")

    def test_weak_features_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            raw=root/"titles.jsonl"
            rows=[dict(display_id=str(i),title="wheat harvest" if i<8 else "football match",categories="A" if i<8 else "B") for i in range(16)]
            raw.write_text("\n".join(json.dumps(x) for x in rows)+"\n")
            source=dict(registry()["youniverse"])
            source.pop("checksum")
            out=build(source,raw,root)
            first=root/"features.jsonl"
            report=title_features(out,first,per_category=4,min_df=2)
            self.assertEqual(report["sample_size_by_category"],{"A":4,"B":4})
            self.assertTrue(any(x["term"]=="wheat harvest" and x["category"]=="A" for x in map(json.loads,first.read_text().splitlines())))
            raw.write_text("\n".join(json.dumps(x) for x in reversed(rows))+"\n")
            other=build(source,raw,root)
            second=root/"other.jsonl"
            title_features(other,second,per_category=4,min_df=2)
            self.assertEqual(first.read_bytes(),second.read_bytes())
            self.assertEqual(Path(str(first)+".samples.jsonl").read_bytes(),Path(str(second)+".samples.jsonl").read_bytes())
            with self.assertRaises(ValueError):
                index_build([out],root/"db.sqlite")
