"""Authenticated discovery prices and account-owned watchlists."""
import asyncio
import math
import re
from typing import Literal
from app.discovery_feeds import crypto_symbol, crypto_prices, india_search, india_prices, us_prices
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, StringConstraints, BeforeValidator
from typing import Annotated
from app.locking import lock_scopes

Symbol = Annotated[str, BeforeValidator(lambda v: v.strip().upper() if isinstance(v, str) else v), StringConstraints(max_length=100, pattern=r'^[A-Z0-9_.:| -]{2,100}$')]

class WatchAsset(BaseModel):
    symbol: Symbol
    market: Literal['crypto','india','us','fo']='crypto'

def make_discovery_router(db, user):
    router = APIRouter(tags=['discovery'])
    cache = {}
    lock = asyncio.Lock()

    @router.get('/api/discovery/prices')
    async def prices(symbols: str = Query('BTCUSDT,ETHUSDT,SOLUSDT', max_length=420), uid=Depends(user)):
        requested=sorted(set(crypto_symbol(s) for s in symbols.split(',')))
        if len(requested)>20:raise HTTPException(422,'Use up to 20 symbols')
        return await cached(('crypto',*requested),lambda:crypto_prices(requested))

    async def cached(key,fetch):
        async with lock:
            if key in cache and time.monotonic()-cache[key][0]<15:return cache[key][1]
            try:payload=await fetch()
            except (ValueError,KeyError,TypeError,OverflowError):raise HTTPException(503,'Market provider returned an invalid quote. Retry shortly.')
            if len(cache)>=128:cache.clear()
            cache[key]=(time.monotonic(),payload)
            return payload

    @router.get('/api/discovery/search')
    async def search(q: str=Query(min_length=2,max_length=50,pattern=r'^[A-Za-z0-9 .&_-]+$'),market: Literal['india','fo']='india',kind: Literal['FUT','CE','PE']='FUT',expiry: str=Query('current_month',max_length=20,pattern=r'^(current_month|next_month|current_week|next_week|\d{4}-\d{2}-\d{2})$'),uid=Depends(user)):
        return await cached(('search',q,market,kind,expiry),lambda:india_search(q,market,kind,expiry))

    @router.get('/api/discovery/quotes')
    async def quotes(market: Literal['india','us','fo'],symbols: str=Query(max_length=2000),uid=Depends(user)):
        values=sorted(set(symbols.upper().split(',')))
        if not 1<=len(values)<=20:raise HTTPException(422,'Use up to 20 instruments')
        if market=='us':
            if any(not re.fullmatch(r'[A-Z][A-Z.-]{0,11}',v) for v in values):raise HTTPException(422,'Enter a US stock ticker such as AAPL')
            return await cached(('us',*values),lambda:us_prices(values))
        segment=r'(NSE|BSE)_FO' if market=='fo' else r'(NSE|BSE)_EQ'
        if any(not re.fullmatch(segment+r'\|[A-Z0-9]{1,30}',v) for v in values):raise HTTPException(422,'Choose an instrument from search results')
        return await cached((market,*values),lambda:india_prices(values))

    @router.get('/api/discovery/watchlist')
    def watchlist(uid=Depends(user)):
        with db() as con:
            return {'symbols': [r['symbol'] for r in con.execute('SELECT symbol FROM watchlist WHERE user_id=? ORDER BY symbol', (uid,)).fetchall()]}

    @router.post('/api/discovery/watchlist')
    def add(payload: WatchAsset, uid=Depends(user)):
        symbol=crypto_symbol(payload.symbol) if payload.market=='crypto' else payload.market.upper()+':'+payload.symbol
        if payload.market=='us' and not re.fullmatch(r'[A-Z][A-Z.-]{0,11}',payload.symbol):raise HTTPException(422,'Invalid US ticker')
        if payload.market in ('india','fo') and not re.fullmatch((r'(NSE|BSE)_FO' if payload.market=='fo' else r'(NSE|BSE)_EQ')+r'\|[A-Z0-9]{1,30}',payload.symbol):raise HTTPException(422,'Select a valid instrument')
        with db() as con:
            lock_scopes(con, f'user:{uid}')
            rows = con.execute('SELECT symbol FROM watchlist WHERE user_id=?', (uid,)).fetchall()
            if symbol not in {r['symbol'] for r in rows}:
                if len(rows) >= 20:
                    raise HTTPException(409, 'Watchlist is limited to 20 pairs')
                con.execute('INSERT INTO watchlist(user_id,symbol) VALUES(?,?)', (uid, symbol))
        return {'symbol': symbol}

    @router.delete('/api/discovery/watchlist/{symbol}')
    def remove(symbol: Symbol, uid=Depends(user)):
        with db() as con:
            con.execute('DELETE FROM watchlist WHERE user_id=? AND symbol=?', (uid, symbol))
        return {'removed': symbol}
    return router
