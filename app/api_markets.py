"""Read-only market data integrations. No order execution."""
import os
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException

def make_markets_router(user):
    router = APIRouter(tags=["market_data"])
    @router.get("/api/markets/providers")
    def market_providers(uid=Depends(user)):
        return {"markets":[
            {"market":"crypto_spot","provider":"binance","available":True,"authentication":"public"},
            {"market":"india_equities_and_fo","provider":"upstox","available":bool(os.getenv("UPSTOX_ACCESS_TOKEN")),"authentication":"server_token"},
            {"market":"us_equities","provider":"alpaca","available":bool(os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_SECRET_KEY")),"authentication":"server_keys"}],
            "execution":"disabled","notice":"Provider entitlements, geographic availability and data licensing apply."}

    @router.get("/api/markets/crypto/candles")
    async def crypto_candles(symbol: str="BTCUSDT", interval: Literal["15m","1h","4h","1d"]="4h", limit: int=100, uid=Depends(user)):
        import re
        import httpx
        if not re.fullmatch(r"[A-Z0-9]{3,20}",symbol) or not 1<=limit<=500:
            raise HTTPException(422,"Invalid symbol or limit")
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response=await client.get("https://data-api.binance.vision/api/v3/klines",
                    params={"symbol":symbol,"interval":interval,"limit":limit})
            response.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(503,"Crypto market provider temporarily unavailable")
        return {"provider":"binance","market":"crypto_spot","symbol":symbol,"interval":interval,
            "candles":[{"timestamp_ms":r[0],"open":float(r[1]),"high":float(r[2]),
                        "low":float(r[3]),"close":float(r[4]),"volume":float(r[5])} for r in response.json()],
            "notice":"Exchange-provided data, not investment advice."}


    @router.get("/api/markets/india/candles")
    async def india_candles(instrument_key: str, unit: Literal["minutes","hours","days"]="days",
        interval: int=1, to_date: str="", from_date: str="", uid=Depends(user)):
        import re
        import httpx
        token=os.getenv("UPSTOX_ACCESS_TOKEN")
        if not token: raise HTTPException(503,"Upstox credentials not configured")
        if not re.fullmatch(r"[A-Z_]+\|[A-Za-z0-9 ._-]{1,90}",instrument_key):
            raise HTTPException(422,"Invalid instrument key")
        if not (1<=interval<=300) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",to_date) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",from_date):
            raise HTTPException(422,"Invalid interval or date")
        from urllib.parse import quote
        url=f"https://api.upstox.com/v3/historical-candle/{quote(instrument_key,safe='')}/{unit}/{interval}/{to_date}/{from_date}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response=await client.get(url,headers={"Authorization":f"Bearer {token}","Accept":"application/json"})
            response.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(502,"Upstox market data unavailable or access denied")
        return {"provider":"upstox","instrument_key":instrument_key,"data":response.json().get("data",{}),
            "notice":"Check instrument entitlements and market data redistribution rights."}

    @router.get("/api/markets/india/option-chain")
    async def india_option_chain(instrument_key: str, expiry_date: str, uid=Depends(user)):
        import re
        import httpx
        token=os.getenv("UPSTOX_ACCESS_TOKEN")
        if not token: raise HTTPException(503,"Upstox credentials not configured")
        if not re.fullmatch(r"[A-Z_]+\|[A-Za-z0-9 ._-]{1,90}",instrument_key) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",expiry_date):
            raise HTTPException(422,"Invalid option-chain query")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response=await client.get("https://api.upstox.com/v2/option/chain",
                    params={"instrument_key":instrument_key,"expiry_date":expiry_date},
                    headers={"Authorization":f"Bearer {token}","Accept":"application/json"})
            response.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(502,"Upstox option chain unavailable or access denied")
        return {"provider":"upstox","data":response.json().get("data",[]),
            "notice":"Option Greeks and POP are vendor estimates, not guaranteed probabilities."}

    @router.get("/api/markets/us/candles")
    async def us_candles(symbol: str="AAPL", timeframe: Literal["1Hour","1Day"]="1Day",
        limit: int=100, uid=Depends(user)):
        import re
        import httpx
        key=os.getenv("ALPACA_API_KEY")
        secret=os.getenv("ALPACA_SECRET_KEY")
        if not key or not secret: raise HTTPException(503,"Alpaca market data credentials not configured")
        if not re.fullmatch(r"[A-Z.]{1,12}",symbol) or not 1<=limit<=500:
            raise HTTPException(422,"Invalid symbol or limit")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response=await client.get(f"https://data.alpaca.markets/v2/stocks/{symbol}/bars",
                    params={"timeframe":timeframe,"limit":limit,"feed":"iex"},
                    headers={"APCA-API-KEY-ID":key,"APCA-API-SECRET-KEY":secret})
            response.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(502,"Alpaca market data unavailable or access denied")
        return {"provider":"alpaca","feed":"iex","symbol":symbol,"data":response.json(),
            "notice":"Free IEX feed is not a consolidated US market feed."}

    return router
