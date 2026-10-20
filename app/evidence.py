"""Shared, owner-scoped evidence retrieval for AI, strategy research and retention."""
from datetime import datetime, timedelta, timezone

QUERIES = {
    "snapshots": "SELECT id,symbol,price,currency,note,kind,recorded_at FROM snapshots WHERE user_id=? ORDER BY id DESC LIMIT ?",
    "decisions": "SELECT d.id,d.price,d.note,d.outcome,d.lesson,d.recorded_at,s.symbol,s.setup,s.side,s.condition,s.trigger_price FROM decisions d JOIN strategies s ON d.strategy_id=s.id WHERE d.user_id=? ORDER BY d.id DESC LIMIT ?",
    "quotes": "SELECT id,symbol,price,currency,recorded_at FROM quotes WHERE user_id=? ORDER BY id DESC LIMIT ?",
}
LIMIT = 30


def load_evidence(con, user_id, limit=LIMIT):
    return {kind: [{**dict(row), "evidence_ref": f"{kind[:-1]}:{row['id']}"}
                   for row in con.execute(sql, (user_id, limit)).fetchall()]
            for kind, sql in QUERIES.items()}


def retention_preview(con, user_id, days=90):
    """Read-only candidate counts. No deletion or assumption of safe archival."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    tables = ("snapshots", "quotes", "decisions")
    counts = {}
    for table in tables:
        row = con.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE user_id=? AND recorded_at<?",
                          (user_id, cutoff)).fetchone()
        counts[table] = row["n"]
    return {"cutoff": cutoff, "candidate_counts": counts,
            "deletion_allowed": False,
            "blocked_by": ["summary verification", "active strategy and hypothesis protection",
                           "dependency checks", "user approval"]}
