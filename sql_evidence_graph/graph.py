"""One SQLite file of entities, relations, and the documents that mention them.

`expand` returns every other document that shares an entity with a seed.
It does not read the question and does not drop a neighbor. `order_by_score`
puts caller-supplied positive scores first. A title lookup reads `documents`
when that table is already in the file; this package does not create it.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    """Replace the graph tables. Any entity type may be linked to a document."""
    conn.executescript(
        """
        DROP TABLE IF EXISTS document_entities;
        DROP TABLE IF EXISTS relation_provenance;
        DROP TABLE IF EXISTS relations;
        DROP TABLE IF EXISTS entities;
        CREATE TABLE entities (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            ref_id TEXT
        );
        CREATE TABLE relations (
            source_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            article_id TEXT,
            method TEXT NOT NULL,
            evidence TEXT
        );
        CREATE INDEX entities_type ON entities (entity_type);
        CREATE INDEX entities_ref ON entities (ref_id);
        CREATE INDEX relations_source ON relations (source_id, relation_type);
        CREATE INDEX relations_target ON relations (target_id, relation_type);
        CREATE INDEX relations_article ON relations (article_id);
        CREATE UNIQUE INDEX relations_edge
            ON relations (source_id, relation_type, target_id, method);
        CREATE TABLE document_entities (
            doc_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            weight REAL NOT NULL CHECK (weight > 0),
            method TEXT NOT NULL,
            evidence TEXT NOT NULL,
            PRIMARY KEY (doc_id, entity_id),
            FOREIGN KEY (doc_id) REFERENCES documents(doc_id),
            FOREIGN KEY (entity_id) REFERENCES entities(id)
        );
        CREATE INDEX document_entities_entity ON document_entities (entity_id, doc_id);
        CREATE TABLE relation_provenance (
            source_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            method TEXT NOT NULL,
            doc_id TEXT,
            weight REAL NOT NULL CHECK (weight > 0),
            evidence TEXT,
            PRIMARY KEY (source_id, relation_type, target_id, method),
            FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
        );
        """
    )


def _record(statements: list | None, statement: str, params: list) -> None:
    if statements is not None:
        statements.append({"statement": " ".join(statement.split()), "params": list(params)})


def expand(graph_path: str | Path, doc_ids: list[str], *, max_hops: int = 1,
           statements: list | None = None) -> list[dict]:
    """Every document that shares an entity with a seed.

    `similarity` is the sum of 1/df over shared entities. `max_hops` below 1
    returns nothing. A larger value still walks one hop: the stored edges
    used here are document-entity links, not a multi-hop path.
    """
    if not doc_ids or max_hops < 1:
        return []
    conn = connect(graph_path)
    try:
        marks = ",".join("?" * len(doc_ids))
        statement = f"""
                WITH seed_entities AS (
                    SELECT DISTINCT entity_id FROM document_entities WHERE doc_id IN ({marks})
                ),
                entity_df AS (
                    SELECT entity_id, COUNT(*) AS df FROM document_entities GROUP BY entity_id
                )
                SELECT n.doc_id AS doc_id,
                       COUNT(DISTINCT n.entity_id) AS shared_count,
                       SUM(1.0 / df.df) AS similarity
                FROM seed_entities s
                JOIN document_entities n ON n.entity_id = s.entity_id
                JOIN entity_df df ON df.entity_id = n.entity_id
                WHERE n.doc_id NOT IN ({marks})
                GROUP BY n.doc_id
                ORDER BY similarity DESC, shared_count DESC, n.doc_id
                """
        params = [*doc_ids, *doc_ids]
        _record(statements, statement, params)
        try:
            rows = conn.execute(statement, params).fetchall()
        except sqlite3.OperationalError:
            rows = []
    finally:
        conn.close()
    return [
        {"doc_id": row["doc_id"], "shared_count": row["shared_count"], "similarity": row["similarity"]}
        for row in rows
    ]


def describe(graph_path: str | Path, seeds: list[str], hits: list[dict],
             statements: list | None = None) -> list[dict]:
    """Title and the rarest shared entity. The chosen hits stay in order."""
    for hit in hits:
        hit.setdefault("title", "")
        hit.setdefault("evidence", "")
        hit.setdefault("method", "body")
        hit.setdefault("reason", "")
        hit.setdefault("seed", None)
        hit.setdefault("entity", None)
    if not hits or not seeds:
        return hits
    conn = connect(graph_path)
    try:
        hit_ids = [hit["doc_id"] for hit in hits]
        hit_marks = ",".join("?" * len(hit_ids))
        seed_marks = ",".join("?" * len(seeds))
        title_sql = f"SELECT doc_id, source FROM documents WHERE doc_id IN ({hit_marks})"
        _record(statements, title_sql, hit_ids)
        try:
            titles = {
                row["doc_id"]: row["source"]
                for row in conn.execute(title_sql, hit_ids)
            }
        except sqlite3.OperationalError:
            titles = {}
        label_sql = f"""
                WITH seed_entities AS (
                    SELECT DISTINCT entity_id FROM document_entities WHERE doc_id IN ({seed_marks})
                ),
                entity_df AS (
                    SELECT entity_id, COUNT(*) AS df FROM document_entities GROUP BY entity_id
                )
                SELECT n.doc_id AS doc_id,
                       ent.name AS entity,
                       n.method AS method,
                       (SELECT s.doc_id FROM document_entities s
                         WHERE s.entity_id = n.entity_id AND s.doc_id IN ({seed_marks})
                         LIMIT 1) AS seed
                FROM document_entities n
                JOIN seed_entities se ON se.entity_id = n.entity_id
                JOIN entities ent ON ent.id = n.entity_id
                JOIN entity_df df ON df.entity_id = n.entity_id
                WHERE n.doc_id IN ({hit_marks})
                ORDER BY n.doc_id, df.df ASC, ent.name
                """
        label_params = [*seeds, *seeds, *hit_ids]
        _record(statements, label_sql, label_params)
        try:
            labels = conn.execute(label_sql, label_params).fetchall()
        except sqlite3.OperationalError:
            labels = []
    finally:
        conn.close()
    label_of = {}
    for row in labels:
        label_of.setdefault(row["doc_id"], row)
    for hit in hits:
        hit["title"] = titles.get(hit["doc_id"], "")
        label = label_of.get(hit["doc_id"])
        if label is None:
            continue
        hit["entity"] = label["entity"]
        hit["seed"] = label["seed"]
        hit["method"] = label["method"]
        hit["reason"] = f"MENTIONS {label['entity']} shared with {label['seed']}"
    return hits


def order_by_score(hits: list[dict], scores: dict[str, float], limit: int = 10) -> list[dict]:
    """Positive scores first, highest first. A missing or non-positive score keeps its place after those."""
    if not hits or limit <= 0:
        return []
    positive = [hit for hit in hits if scores.get(hit["doc_id"], 0) > 0]
    positive.sort(key=lambda hit: (-scores[hit["doc_id"]], hit["doc_id"]))
    rest = [hit for hit in hits if scores.get(hit["doc_id"], 0) <= 0]
    return (positive + rest)[:limit]


class EvidenceGraph:
    """A graph file. `link` records that a document mentions an entity."""

    def __init__(self, path: str | Path):
        self.path = path

    def create(self) -> None:
        conn = connect(self.path)
        try:
            create_schema(conn)
            conn.commit()
        finally:
            conn.close()

    def link(self, doc_id: str, entity_id: str, name: str, entity_type: str,
             method: str, evidence: str, weight: float = 1.0) -> None:
        conn = connect(self.path)
        try:
            conn.execute(
                """INSERT INTO entities (id, name, entity_type, ref_id) VALUES (?, ?, ?, NULL)
                   ON CONFLICT(id) DO NOTHING""",
                (entity_id, name, entity_type),
            )
            conn.execute(
                """INSERT INTO document_entities (doc_id, entity_id, weight, method, evidence)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(doc_id, entity_id) DO UPDATE SET
                     weight=excluded.weight, method=excluded.method, evidence=excluded.evidence""",
                (doc_id, entity_id, weight, method, evidence),
            )
            conn.commit()
        finally:
            conn.close()

    def expand(self, seed_ids: list[str], *, max_hops: int = 1, statements: list | None = None) -> list[dict]:
        return expand(self.path, seed_ids, max_hops=max_hops, statements=statements)

    def describe(self, seeds: list[str], hits: list[dict], statements: list | None = None) -> list[dict]:
        return describe(self.path, seeds, hits, statements=statements)
