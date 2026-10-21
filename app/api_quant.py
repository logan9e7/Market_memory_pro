"""Quantitative HTTP boundary; all calculations delegated to a tested service."""
from typing import Literal
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from app import quant_hybrid

class TradeSample(BaseModel):
    returns: list[float] = Field(min_length=1,max_length=10000)
    @field_validator("returns")
    @classmethod
    def valid_returns(cls, values):
        if any(not -1 < x < 1000 for x in values):
            raise ValueError("Returns must be finite decimal fractions greater than -100%")
        return values

class OptionModel(BaseModel):
    spot: float = Field(gt=0,allow_inf_nan=False)
    strike: float = Field(gt=0,allow_inf_nan=False)
    years: float = Field(gt=0,le=30,allow_inf_nan=False)
    rate: float = Field(ge=-1,le=2,allow_inf_nan=False)
    volatility: float = Field(gt=0,le=10,allow_inf_nan=False)
    kind: Literal["call","put"]

def make_quant_router(authenticate):
    router=APIRouter(prefix="/api/quant",tags=["quant"])
    @router.post("/trades")
    def trades(payload:TradeSample,uid=Depends(authenticate)):
        return quant_hybrid.trade_stats(payload.returns)
    @router.post("/option")
    def option(payload:OptionModel,uid=Depends(authenticate)):
        return quant_hybrid.black_scholes(**payload.model_dump())
    return router
