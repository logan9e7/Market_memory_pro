"""Deterministic AI evidence selection and provenance checks.

This module never invents financial facts or calls a model. It prepares
owner-scoped evidence from the existing database for an LLM.
"""
from dataclasses import dataclass
from typing import Mapping

ALLOWED_KINDS=frozenset({"snapshots","decisions","quotes"})

@dataclass(frozen=True)
class EvidenceRef:
    kind: str
    record_id: int
    user_id: int

def prepare_evidence(evidence:Mapping, user_id:int, max_per_kind:int=20):
    if user_id<=0 or max_per_kind<1 or max_per_kind>100:
        raise ValueError("Invalid evidence retrieval scope")
    selected={}
    for kind in ALLOWED_KINDS:
        rows=evidence.get(kind,[])
        if not isinstance(rows,list):
            raise ValueError("Invalid evidence format")
        output=[]
        for row in rows[:max_per_kind]:
            if not isinstance(row,dict) or not isinstance(row.get("id"),int):
                raise ValueError("Evidence must include an integer record ID")
            if "user_id" in row and row["user_id"]!=user_id:
                raise PermissionError("Cross-user evidence is forbidden")
            expected=f"{kind[:-1]}:{row['id']}"
            if row.get("evidence_ref",expected)!=expected:
                raise ValueError("Evidence reference mismatch")
            output.append({**row,"evidence_ref":expected})
        selected[kind]=output
    return selected
