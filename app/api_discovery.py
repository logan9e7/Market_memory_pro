"""Authenticated discovery prices and account-owned watchlists."""
import asyncio
import math
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, StringConstraints, BeforeValidator
from typing import Annotated
from app.locking import lock_scopes

Symbol = Annotated[str, BeforeValidator(lambda v: v.strip().upper() if isinstance(v, str) else v), StringConstraints(pattern=r'^[A-Z0-9]{3,20}$')]

class WatchAsset(BaseModel):
    symbol: Symbol

def make_discovery_router(db, user):
    router = APIRouter(tags=['discovery'])
    cache = {}
    lock = asyncio.Lock()

    @router.get('/api/discovery/prices')
    async def prices(symbols: str = Query('BTCUSDT,ETHUSDT,SOLUSDT', max_length=420), uid=Depends(user)):
        import json
        import re
        requested = sorted(set(symbols.upper().split(',')))
        if not 1 <= len(requested) <= 20 or any(not re.fullmatch(r'[A-Z0-9]{3,20}', s) for s in requested):
            raise HTTPException(422, 'Use up to 20 crypto pair symbols')
        key = tuple(requested)
        async with lock:
            if key in cache and time.monotonic() - cache[key][0] < 15:
                return cache[key][1]
            try:
                async with httpx.AsyncClient(timeout=8) as client:
                    response = await client.get('https://data-api.binance.vision/api/v3/ticker/24hr', params={'symbols': json.dumps(requested)})
                if response.status_code == 400:
                    raise HTTPException(422, 'Unknown crypto pair. Try BTCUSDT or ETHUSDT.')
                response.raise_for_status()
                result = []
                for row in response.json():
                    item = {'symbol': row['symbol'], 'price': float(row['lastPrice']), 'change_percent': float(row['priceChangePercent']), 'high': float(row['highPrice']), 'low': float(row['lowPrice']), 'volume': float(row['volume']), 'as_of': datetime.fromtimestamp(int(row['closeTime']) / 1000, timezone.utc).isoformat()}
                    if not all(math.isfinite(item[k]) for k in ('price','change_percent','high','low','volume')) or item['price'] <= 0:
                        raise ValueError('Invalid quote')
                    result.append(item)
                payload = {'provider': 'Binance spot', 'quotes': result, 'fetched_at': datetime.now(timezone.utc).isoformat()}
            except (httpx.HTTPError, ValueError, KeyError, TypeError, OverflowError):
                raise HTTPException(503, 'Live prices unavailable. Retry shortly; no replacement prices are shown.')
            if len(cache) >= 128:
                cache.clear()
            cache[key] = (time.monotonic(), payload)
            return payload

    @router.get('/api/discovery/watchlist')
    def watchlist(uid=Depends(user)):
        with db() as con:
            return {'symbols': [r['symbol'] for r in con.execute('SELECT symbol FROM watchlist WHERE user_id=? ORDER BY symbol', (uid,)).fetchall()]}

    @router.post('/api/discovery/watchlist')
    def add(payload: WatchAsset, uid=Depends(user)):
        with db() as con:
            lock_scopes(con, f'user:{uid}')
            rows = con.execute('SELECT symbol FROM watchlist WHERE user_id=?', (uid,)).fetchall()
            if payload.symbol not in {r['symbol'] for r in rows}:
                if len(rows) >= 20:
                    raise HTTPException(409, 'Watchlist is limited to 20 pairs')
                con.execute('INSERT INTO watchlist(user_id,symbol) VALUES(?,?)', (uid, payload.symbol))
        return {'symbol': payload.symbol}

    @router.delete('/api/discovery/watchlist/{symbol}')
    def remove(symbol: Symbol, uid=Depends(user)):
        with db() as con:
            con.execute('DELETE FROM watchlist WHERE user_id=? AND symbol=?', (uid, symbol))
        return {'removed': symbol}
    return router
