# sql-evidence-graph

SQLite evidence graph. One hop from seed documents along shared entities. The caller supplies scores. This package does not embed text, stem words, or call a model.

```python
from sql_evidence_graph import EvidenceGraph, order_by_score

graph = EvidenceGraph("knowledge.db")
graph.create()
graph.link("doc-1", "feature:payments", "payments", "feature", "body", "payments settle overnight")
neighbors = graph.expand(["doc-1"])
ordered = order_by_score(neighbors, {"doc-2": 1.5})
```

`expand` returns every other document that shares an entity. It does not read the question and does not drop a neighbor. `order_by_score` puts positive caller scores first.
