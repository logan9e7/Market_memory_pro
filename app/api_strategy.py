"""Owner-scoped alerts, paper-only approvals and state APIs."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.models import Alert
from app.config import MIN_REVIEWS

def make_strategy_router(db, user, now, audit, latest, fresh, matches, stats, evaluate):
    router=APIRouter(tags=["strategies"])
    @router.post("/api/alerts", status_code=201)
    def create_alert(payload: Alert, uid=Depends(user)):
        with db() as con:
            con.execute("BEGIN IMMEDIATE")
            aid = con.execute("INSERT INTO alerts(user_id,symbol,currency,condition,target) VALUES(?,?,?,?,?)", (uid, payload.symbol.upper(), payload.currency, payload.condition, payload.target)).lastrowid
            quote = latest(con, uid, payload.symbol.upper(), payload.currency)
            if fresh(quote):
                evaluate(con, uid, quote)
        return {"id": aid}

    class Approval(BaseModel):
        action: Literal["approve", "reject"]
        quantity: float = Field(default=1, gt=0, le=1000000, allow_inf_nan=False)
        expected_quote_id: int | None = Field(default=None, gt=0)

    @router.post("/api/opportunities/{opportunity_id}/approval")
    def approval(opportunity_id: int, payload: Approval, uid=Depends(user)):
        with db() as con:
            con.execute("BEGIN IMMEDIATE")
            opportunity = con.execute("SELECT * FROM opportunities WHERE id=? AND user_id=?", (opportunity_id, uid)).fetchone()
            if not opportunity:
                raise HTTPException(404, "Opportunity not found")
            if opportunity["status"] == "approved" and payload.action == "approve":
                order = con.execute("SELECT * FROM paper_orders WHERE opportunity_id=?", (opportunity_id,)).fetchone()
                if order["quantity"] != payload.quantity:
                    raise HTTPException(409, "Already approved with a different quantity")
                return {"status": "approved", "mode": "paper", "order": dict(order)}
            if opportunity["status"] == "rejected" and payload.action == "reject":
                return {"status": "rejected"}
            if opportunity["status"] != "pending":
                raise HTTPException(409, "Opportunity is no longer pending")
            if payload.action == "reject":
                con.execute("UPDATE opportunities SET status='rejected',decided_at=? WHERE id=?", (now(), opportunity_id))
                audit(con, uid, "permission_rejected", opportunity_id, {})
                return {"status": "rejected"}
            rule = con.execute("SELECT * FROM strategies WHERE id=?", (opportunity["strategy_id"],)).fetchone()
            quote = latest(con, uid, rule["symbol"], rule["currency"])
            if not fresh(quote) or not matches(rule, quote["price"]) or not stats(con, rule["id"])["eligible"]:
                raise HTTPException(409, "Evidence or price changed; record a fresh matching price and reassess")
            if payload.expected_quote_id != quote["id"]:
                raise HTTPException(409, "Price changed since this proposal was displayed; refresh before approving")
            con.execute("UPDATE opportunities SET status='approved',decided_at=? WHERE id=?", (now(), opportunity_id))
            oid = con.execute("INSERT INTO paper_orders(user_id,opportunity_id,quantity,reference_price,recorded_at) VALUES(?,?,?,?,?)", (uid, opportunity_id, payload.quantity, quote["price"], now())).lastrowid
            audit(con, uid, "paper_execution_approved", opportunity_id, {"quantity": payload.quantity, "quote_id": quote["id"], "paper_order_id": oid})
            order = con.execute("SELECT * FROM paper_orders WHERE id=?", (oid,)).fetchone()
        return {"status": "approved", "mode": "paper", "order": dict(order)}

    @router.get("/api/state")
    def state(uid=Depends(user)):
        with db() as con:
            strategies = []
            for row in con.execute("SELECT * FROM strategies WHERE user_id=? ORDER BY id DESC", (uid,)).fetchall():
                strategies.append({**dict(row), **stats(con, row["id"])})
            queries = {
                "quotes": "SELECT * FROM quotes WHERE id IN (SELECT MAX(id) FROM quotes WHERE user_id=? GROUP BY symbol,currency) ORDER BY id DESC",
                "snapshots": "SELECT s.*,q.recorded_at AS quote_recorded_at FROM snapshots s LEFT JOIN quotes q ON s.quote_id=q.id WHERE s.user_id=? ORDER BY s.id DESC LIMIT 200",
                "visits": "SELECT * FROM visits WHERE user_id=? ORDER BY id DESC LIMIT 50",
                "decisions": "SELECT d.*,s.symbol,s.currency,s.setup,s.side FROM decisions d JOIN strategies s ON d.strategy_id=s.id WHERE d.user_id=? ORDER BY d.id DESC LIMIT 200",
                "alerts": "SELECT * FROM alerts WHERE user_id=? ORDER BY id DESC LIMIT 200",
                "opportunities": "SELECT o.*,s.symbol,s.currency,s.setup,s.side,s.condition,s.trigger_price,q.price FROM opportunities o JOIN strategies s ON o.strategy_id=s.id JOIN quotes q ON o.quote_id=q.id WHERE o.user_id=? ORDER BY o.id DESC LIMIT 100",
                "paper_orders": "SELECT p.*,s.symbol,s.currency,s.side FROM paper_orders p JOIN opportunities o ON p.opportunity_id=o.id JOIN strategies s ON o.strategy_id=s.id WHERE p.user_id=? ORDER BY p.id DESC LIMIT 100",
                "audit": "SELECT * FROM audit_events WHERE user_id=? ORDER BY id DESC LIMIT 100",
            }
            result = {key: [dict(row) for row in con.execute(sql, (uid,)).fetchall()] for key, sql in queries.items()}
            result.update(username=con.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()[0], strategies=strategies, minimum_reviews=MIN_REVIEWS, execution_mode="paper")
        return result


    return router
