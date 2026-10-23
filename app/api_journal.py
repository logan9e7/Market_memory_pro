"""User-owned, transactional journal and review endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from app.models import Quote, Snapshot, Visit, Decision, Review
from app.locking import lock_scopes

def make_journal_router(db, user, now, audit, evaluate, latest):
    router = APIRouter(tags=["journal"])
    @router.post("/api/quotes", status_code=201)
    def record_quote(payload: Quote, uid=Depends(user)):
        with db() as con:
            lock_scopes(con, f"user:{uid}")
            qid = con.execute("INSERT INTO quotes(user_id,symbol,price,currency,recorded_at) VALUES(?,?,?,?,?)", (uid, payload.symbol, payload.price, payload.currency, now())).lastrowid
            quote = con.execute("SELECT * FROM quotes WHERE id=?", (qid,)).fetchone()
            evaluate(con, uid, quote)
        return dict(quote)

    def snapshot_row(con, uid, quote, note, kind, visit_id=None):
        return con.execute("INSERT INTO snapshots(user_id,symbol,price,currency,quote_id,note,kind,visit_id,recorded_at) VALUES(?,?,?,?,?,?,?,?,?)", (uid, quote["symbol"], quote["price"], quote["currency"], quote["id"], note, kind, visit_id, now())).lastrowid

    @router.post("/api/snapshots", status_code=201)
    def manual_snapshot(payload: Snapshot, uid=Depends(user)):
        with db() as con:
            quote = latest(con, uid, payload.symbol.upper())
            if not quote:
                raise HTTPException(409, "Record a price for this asset first")
            sid = snapshot_row(con, uid, quote, payload.note, "manual")
        return {"id": sid}

    @router.post("/api/visits")
    def record_visit(payload: Visit, uid=Depends(user)):
        with db() as con:
            lock_scopes(con, f"user:{uid}")
            existing = con.execute("SELECT id FROM visits WHERE user_id=? AND event_id=?", (uid, payload.event_id)).fetchone()
            if existing:
                return {"id": existing["id"], "duplicate": True}
            vid = con.execute("INSERT INTO visits(user_id,event_id,kind,recorded_at) VALUES(?,?,?,?)", (uid, payload.event_id, payload.kind, now())).lastrowid
            quotes = con.execute("SELECT * FROM quotes WHERE id IN (SELECT MAX(id) FROM quotes WHERE user_id=? GROUP BY symbol,currency)", (uid,)).fetchall()
            for quote in quotes:
                snapshot_row(con, uid, quote, "Last recorded user price; not a new market quote", payload.kind, vid)
        return {"id": vid, "captured": len(quotes)}

    @router.post("/api/decisions", status_code=201)
    def record_decision(payload: Decision, uid=Depends(user)):
        with db() as con:
            lock_scopes(con, f"user:{uid}")
            existing = con.execute("SELECT d.*,s.symbol,s.currency,s.setup,s.side,s.condition,s.trigger_price FROM decisions d JOIN strategies s ON d.strategy_id=s.id WHERE d.user_id=? AND d.request_id=?", (uid, payload.request_id)).fetchone()
            if existing:
                expected = (payload.symbol, payload.currency, payload.setup.casefold(), payload.side, payload.condition, payload.trigger_price, payload.price, payload.note)
                actual = tuple(existing[key] for key in ("symbol", "currency", "setup", "side", "condition", "trigger_price", "price", "note"))
                if actual != expected:
                    raise HTTPException(409, "This request ID belongs to a different decision")
                return {"id": existing["id"], "duplicate": True}
            key = (uid, payload.symbol, payload.currency, payload.setup.casefold(), payload.side, payload.condition, payload.trigger_price)
            con.execute("INSERT OR IGNORE INTO strategies(user_id,symbol,currency,setup,side,condition,trigger_price) VALUES(?,?,?,?,?,?,?)", key)
            strategy = con.execute("SELECT id FROM strategies WHERE user_id=? AND symbol=? AND currency=? AND setup=? AND side=? AND condition=? AND trigger_price=?", key).fetchone()
            did = con.execute("INSERT INTO decisions(user_id,strategy_id,price,note,recorded_at,request_id) VALUES(?,?,?,?,?,?)", (uid, strategy["id"], payload.price, payload.note, now(), payload.request_id)).lastrowid
            audit(con, uid, "decision_recorded", did, {"strategy_id": strategy["id"]})
        return {"id": did, "strategy_id": strategy["id"]}

    @router.post("/api/decisions/{decision_id}/review")
    def review_decision(decision_id: int, payload: Review, uid=Depends(user)):
        with db() as con:
            lock_scopes(con, f"user:{uid}")
            decision = con.execute("SELECT * FROM decisions WHERE id=? AND user_id=?", (decision_id, uid)).fetchone()
            if not decision:
                raise HTTPException(404, "Decision not found")
            if decision["outcome"]:
                if decision["outcome"] == payload.outcome and decision["lesson"] == payload.lesson:
                    return {"status": "reviewed"}
                raise HTTPException(409, "Completed outcomes cannot be rewritten")
            con.execute("UPDATE decisions SET outcome=?,lesson=?,reviewed_at=? WHERE id=?", (payload.outcome, payload.lesson, now(), decision_id))
            audit(con, uid, "outcome_reviewed", decision_id, {"outcome": payload.outcome})
            rule = con.execute("SELECT * FROM strategies WHERE id=?", (decision["strategy_id"],)).fetchone()
            quote = latest(con, uid, rule["symbol"], rule["currency"])
            if quote:
                evaluate(con, uid, quote)
        return {"status": "reviewed"}

    return router
