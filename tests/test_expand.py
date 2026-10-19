"""One hop returns every neighbor. A caller score reorders them. Any entity type can be linked."""
import sqlite3
import tempfile
import unittest

from sql_evidence_graph import EvidenceGraph, order_by_score


class ExpandTests(unittest.TestCase):
    def test_a_topic_link_expands_and_a_positive_score_leads(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = EvidenceGraph(f"{directory}/graph.sqlite3")
            graph.create()
            graph.link("seed", "topic:payments", "payments", "topic", "body", "payments settle overnight")
            graph.link("neighbor", "topic:payments", "payments", "topic", "body", "settlement window")
            statements = []
            found = graph.expand(["seed"], statements=statements)
            described = graph.describe(["seed"], found, statements=statements)
        self.assertEqual([hit["doc_id"] for hit in found], ["neighbor"])
        self.assertEqual(described[0]["entity"], "payments")
        self.assertEqual(len(statements), 3)
        self.assertIn("document_entities", statements[0]["statement"])
        self.assertEqual(statements[0]["params"], ["seed", "seed"])
        self.assertTrue(statements[1]["statement"].startswith("SELECT doc_id, source FROM documents"))
        ordered = order_by_score(
            [{"doc_id": "neighbor", "similarity": 1.0}, {"doc_id": "other", "similarity": 9.0}],
            {"other": 2.0},
            limit=10,
        )
        self.assertEqual([hit["doc_id"] for hit in ordered], ["other", "neighbor"])


class SchemaTests(unittest.TestCase):
    def test_create_leaves_no_catalog_trigger(self):
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/graph.sqlite3"
            EvidenceGraph(path).create()
            conn = sqlite3.connect(path)
            names = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")]
            conn.close()
        self.assertEqual(names, [])


if __name__ == "__main__":
    unittest.main()
