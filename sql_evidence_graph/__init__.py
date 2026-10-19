"""Expand an existing search result along stored document-entity links.

The caller owns the index and the ranker. This package does not embed text,
stem words, or call a model.
"""
from sql_evidence_graph.graph import EvidenceGraph, create_schema, describe, expand, order_by_score

__all__ = ["EvidenceGraph", "create_schema", "describe", "expand", "order_by_score"]
