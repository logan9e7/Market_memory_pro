"""Research lab routes (no live execution)."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

def make_lab_router(db, user, now, audit):
    router=APIRouter(tags=["research_lab"])
    class LabIdea(BaseModel):
        title: str = Field(min_length=3, max_length=120)
        hypothesis: str = Field(min_length=10, max_length=5000)
        symbol: str = Field(min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9.^_-]+$")
        timeframe: Literal["15m", "1h", "4h", "1d", "1w"] = "4h"

    class LabNote(BaseModel):
        content: str = Field(min_length=1, max_length=5000)

    @router.get("/api/lab")
    def lab_list(uid=Depends(user)):
        with db() as con:
            ideas = [dict(r) for r in con.execute("SELECT * FROM lab_ideas WHERE user_id=? ORDER BY id DESC LIMIT 100", (uid,)).fetchall()]
            notes = [dict(r) for r in con.execute("SELECT * FROM lab_notes WHERE user_id=? ORDER BY id DESC LIMIT 300", (uid,)).fetchall()]
        return {"ideas": ideas, "notes": notes, "mode": "research_only"}

    @router.post("/api/lab", status_code=201)
    def lab_create(payload: LabIdea, uid=Depends(user)):
        with db() as con:
            idea_id = con.execute("INSERT INTO lab_ideas(user_id,title,hypothesis,symbol,timeframe,created_at) VALUES(?,?,?,?,?,?)",
                (uid,payload.title.strip(),payload.hypothesis.strip(),payload.symbol.upper(),payload.timeframe,now())).lastrowid
            audit(con, uid, "lab_idea_created", idea_id, {"symbol":payload.symbol.upper()})
        return {"id": idea_id, "status": "draft"}

    @router.post("/api/lab/{idea_id}/notes", status_code=201)
    def lab_add_note(idea_id: int, payload: LabNote, uid=Depends(user)):
        with db() as con:
            idea = con.execute("SELECT id FROM lab_ideas WHERE id=? AND user_id=?", (idea_id,uid)).fetchone()
            if not idea: raise HTTPException(404,"Strategy draft not found")
            note_id = con.execute("INSERT INTO lab_notes(idea_id,user_id,role,content,created_at) VALUES(?,?,?,?,?)",
                (idea_id,uid,"user",payload.content.strip(),now())).lastrowid
            audit(con,uid,"lab_note_added",idea_id,{"note_id":note_id})
        return {"id":note_id}

    @router.get("/api/lab/{idea_id}/evidence")
    def lab_evidence(idea_id: int, uid=Depends(user)):
        # Transparent lexical baseline. No fabricated embeddings, LLM, or backtest claims.
        with db() as con:
            idea=con.execute("SELECT * FROM lab_ideas WHERE id=? AND user_id=?", (idea_id,uid)).fetchone()
            if not idea: raise HTTPException(404,"Strategy draft not found")
            decisions=con.execute("""SELECT d.id,d.note,d.outcome,d.lesson,s.setup,s.symbol
                FROM decisions d JOIN strategies s ON s.id=d.strategy_id
                WHERE d.user_id=? AND s.symbol=? ORDER BY d.id DESC LIMIT 100""",
                (uid,idea["symbol"])).fetchall()
        # Keep this endpoint as an explicit evidence retriever, not a second AI analyst.
        # The shared LLM engine can interpret these records after retrieval.
        return {"method": "symbol-filtered recent evidence",
                "evidence": [dict(row) for row in decisions[:10]],
                "limitations": "Recent records only; not ranked for relevance or statistically validated."}


    return router
