"""Evidence-grounded AI and retention API boundary."""
import json
import os
from fastapi import APIRouter, Depends, HTTPException
from app.intelligence import analyze_evidence
from app.evidence import load_evidence, retention_preview
from app.ai_evidence import prepare_evidence
from app.retention import RETENTION

def make_intelligence_router(user, db, now):
    router = APIRouter(tags=["intelligence"])
    REPORT_HISTORY_LIMIT = 10

    @router.post("/api/intelligence/analyze")
    async def intelligence_analyze(uid=Depends(user)):
        """Analyze only this user's recent evidence; never send passwords or tokens."""
        with db() as con:
            evidence = prepare_evidence(load_evidence(con, uid), uid, max_per_kind=30)
        if not any(evidence.values()):
            raise HTTPException(409, "Record a journal entry or price snapshot before analysis")
        try:
            report = await analyze_evidence(evidence)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        except Exception:
            # Do not expose model provider credentials or user journal text in errors.
            raise HTTPException(502, "Analysis provider unavailable or returned invalid data")
        with db() as con:
            report_id = con.execute(
                "INSERT INTO analysis_reports(user_id,model,report_json,created_at) VALUES(?,?,?,?)",
                (uid, os.getenv("LLM_MODEL", "gpt-4o-mini"), report.model_dump_json(), now())
            ).lastrowid
        return {"id": report_id, "analysis": report.model_dump(), "source_counts": {k: len(v) for k,v in evidence.items()}}

    @router.get("/api/intelligence/history")
    def intelligence_history(uid=Depends(user)):
        with db() as con:
            rows = con.execute(
                "SELECT id,model,report_json,created_at FROM analysis_reports WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, REPORT_HISTORY_LIMIT)
            ).fetchall()
        return {"reports": [{"id": r["id"], "model": r["model"], "created_at": r["created_at"],
                             "analysis": json.loads(r["report_json"])} for r in rows]}

    @router.get("/api/intelligence/evolution")
    def intelligence_evolution(uid=Depends(user)):
        """Compare evidence-backed parameter observations across the last two reports."""
        with db() as con:
            rows = con.execute(
                "SELECT id,report_json,created_at FROM analysis_reports WHERE user_id=? ORDER BY id DESC LIMIT 2",
                (uid,)).fetchall()
        if len(rows) < 2:
            return {"status": "insufficient_history", "required_reports": 2, "available": len(rows)}
        recent, previous = (json.loads(row["report_json"]) for row in rows)
        levels = ("level_1_evidence", "level_2_quantitative", "level_3_behavior", "level_5_adaptation")
        def parameters(report):
            return {(level, item["parameter"]): item for level in levels
                    for item in report.get(level, []) if item.get("parameter")}
        current, prior = parameters(recent), parameters(previous)
        keys = current.keys() | prior.keys()
        return {
            "status": "compared",
            "current_report_id": rows[0]["id"],
            "previous_report_id": rows[1]["id"],
            "added": [{"level": k[0], **current[k]} for k in sorted(keys) if k in current and k not in prior],
            "missing": [{"level": k[0], **prior[k]} for k in sorted(keys) if k in prior and k not in current],
            "revisited": [{"level": k[0], "parameter": k[1],
                           "previous": prior[k]["observation"], "current": current[k]["observation"]}
                          for k in sorted(keys) if k in prior and k in current
                          and prior[k]["observation"] != current[k]["observation"]],
            "notice": "Changes in LLM descriptions are not proof of behavior change. Verify against source records."
        }

    @router.get("/api/account/retention")
    def retention_settings(uid=Depends(user)):
        return {"raw_days": RETENTION.raw_days, "summary_days": RETENTION.summary_days,
                "deletion_mode": RETENTION.deletion_mode,
                "preserve_active_strategy_evidence": RETENTION.preserve_active_strategy_evidence,
                "deletion_enabled": RETENTION.deletion_enabled,
                "notice": "Retention is configured; no data will be deleted until verified archival and approval are implemented."}

    @router.get("/api/account/retention/preview")
    def retention_candidates(uid=Depends(user)):
        with db() as con:
            return retention_preview(con, uid, RETENTION.raw_days)

    return router
