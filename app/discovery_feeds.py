"""Provider adapters: preserve currency, venue and quote timestamps."""
import asyncio
import json
import math
import os
import re
from datetime import datetime, timezone
import httpx
from fastapi import HTTPException


def stamp(value=None):
    return datetime.fromtimestamp(float(value)/1000, timezone.utc).isoformat() if value else datetime.now(timezone.utc).isoformat()


def crypto_symbol(value):
    value=value.strip().upper()
    value={'BITCOIN':'BTC','ETHEREUM':'ETH','SOLANA':'SOL','RAYDIUM':'RAY'}.get(value,value)
    if not re.fullmatch(r'[A-Z0-9]{2,20}',value):
        raise HTTPException(422,'Enter a crypto ticker such as RAY or a pair such as RAYUSDT')
    if not any(value.endswith(q) and len(value)>len(q) for q in ('USDT','USDC','USD','EUR','BTC','ETH','BNB')):
        value+='USDT'
    return value


def valid_quote(item):
    for field in ('price','high','low','volume','change_percent'):
        if item.get(field) is not None and not math.isfinite(float(item[field])):
            raise ValueError('Invalid quote')
    if float(item['price'])<=0:
        raise ValueError('Invalid price')
    return item


async def crypto_prices(symbols):
    errors=[]
    async with httpx.AsyncClient(timeout=12) as client:
        try:
            response=await client.get('https://data-api.binance.vision/api/v3/ticker/24hr',params={'symbols':json.dumps(symbols,separators=(',',':'))})
            response.raise_for_status()
            rows=response.json()
            result=[valid_quote({'symbol':r['symbol'],'price':float(r['lastPrice']),'change_percent':float(r['priceChangePercent']),'high':float(r['highPrice']),'low':float(r['lowPrice']),'volume':float(r['volume']),'as_of':stamp(r['closeTime']),'provider':'Binance spot','currency':next((q for q in ('USDT','USDC','USD','EUR','BTC','ETH','BNB') if r['symbol'].endswith(q)),''),'period':'24h'}) for r in rows]
            if not result:raise ValueError('Empty provider response')
            return {'quotes':result,'errors':[],'provider':'Binance spot','fetched_at':stamp()}
        except (httpx.HTTPError,ValueError,KeyError,TypeError,OverflowError):
            pass
        gate=asyncio.Semaphore(4)
        async def fallback(symbol):
            async with gate:
                # Kraken is a distinct venue; never relabel USD as USDT.
                pair='XBT'+symbol[3:] if symbol.startswith('BTC') else symbol
                try:
                    response=await client.get('https://api.kraken.com/0/public/Ticker',params={'pair':pair})
                    response.raise_for_status()
                    data=response.json()
                    if data.get('error'):
                        errors.append({'symbol':symbol,'message':'Pair not found or unavailable on the fallback exchange'});return None
                    row=next(iter(data['result'].values()))
                    return valid_quote({'symbol':symbol,'price':float(row['c'][0]),'change_percent':None,'high':float(row['h'][1]),'low':float(row['l'][1]),'volume':float(row['v'][1]),'as_of':stamp(),'timestamp_kind':'retrieved','provider':'Kraken spot · fallback','currency':next((q for q in ('USDT','USDC','USD','EUR','BTC','ETH','BNB') if symbol.endswith(q)),''),'period':'24h'})
                except (httpx.HTTPError,ValueError,KeyError,TypeError,StopIteration,OverflowError):
                    errors.append({'symbol':symbol,'message':'Both exchange feeds are unavailable'});return None
        result=[r for r in await asyncio.gather(*(fallback(s) for s in symbols)) if r]
    if not result:
        raise HTTPException(503,'Crypto feeds unavailable for these pairs. Try BTCUSDT or another pair; Binance and Kraken returned no usable quotes.')
    return {'quotes':result,'errors':errors,'provider':'Kraken spot · fallback','fetched_at':stamp()}


def upstox_headers():
    token=os.getenv('UPSTOX_ACCESS_TOKEN')
    if not token:raise HTTPException(503,'Indian stocks and F&O need an Upstox connection. Set UPSTOX_ACCESS_TOKEN securely on the server; no prices are fabricated.')
    return {'Authorization':f'Bearer {token}','Accept':'application/json'}


async def upstox_get(path,params):
    headers=upstox_headers()
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r=await client.get('https://api.upstox.com/v2/'+path,params=params,headers=headers)
        if r.status_code in (401,403):raise HTTPException(503,'Upstox access expired or lacks market-data permission. Renew the server access token.')
        r.raise_for_status()
        data=r.json()
        if data.get('status')!='success':raise ValueError('Provider failure')
        return data
    except (httpx.HTTPError,ValueError,KeyError,TypeError):
        raise HTTPException(503,'Upstox market data temporarily unavailable. Retry shortly.')


async def india_search(query,market,kind,expiry):
    params={'query':query,'exchanges':'NSE,BSE','segments':'FO' if market=='fo' else 'EQ','records':20}
    if market=='fo':
        params['segments']='FUT' if kind=='FUT' else 'OPT'
        if kind in ('CE','PE'):params['instrument_types']=kind
        params['expiry']=expiry or 'current_month'
    data=await upstox_get('instruments/search',params)
    return {'instruments':[{'symbol':r['trading_symbol'],'instrument_key':r['instrument_key'],'name':r.get('name',''),'kind':r.get('instrument_type',''),'expiry':r.get('expiry'),'strike':r.get('strike_price'),'lot_size':r.get('lot_size'),'exchange':r.get('exchange')} for r in data.get('data',[])][:20]}


async def india_prices(keys):
    data=await upstox_get('market-quote/quotes',{'instrument_key':','.join(keys)})
    result=[]
    for r in data.get('data',{}).values():
        price=float(r['last_price']);change=float(r.get('net_change',0));previous=price-change
        result.append(valid_quote({'symbol':r.get('symbol',r['instrument_token']),'instrument_key':r['instrument_token'],'price':price,'currency':'INR','change_percent':change/previous*100 if previous>0 else None,'high':r.get('ohlc',{}).get('high'),'low':r.get('ohlc',{}).get('low'),'volume':r.get('volume'),'open_interest':r.get('oi'),'as_of':stamp(r['last_trade_time']) if r.get('last_trade_time') else r.get('timestamp'),'provider':'Upstox · exchange snapshot','period':'session'}))
    return {'quotes':result,'provider':'Upstox','fetched_at':stamp(),'errors':[]}


async def us_prices(symbols):
    key,secret=os.getenv('ALPACA_API_KEY'),os.getenv('ALPACA_SECRET_KEY')
    if not key or not secret:raise HTTPException(503,'US stocks need an Alpaca market-data connection. Set ALPACA_API_KEY and ALPACA_SECRET_KEY securely on the server. Free IEX quotes cover one exchange.')
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r=await client.get('https://data.alpaca.markets/v2/stocks/snapshots',params={'symbols':','.join(symbols),'feed':'iex'},headers={'APCA-API-KEY-ID':key,'APCA-API-SECRET-KEY':secret})
        if r.status_code in (401,403):raise HTTPException(503,'Alpaca credentials expired or market-data permission is missing.')
        r.raise_for_status();result=[]
        for symbol,row in r.json().items():
            trade=row.get('latestTrade') or {};bar=row.get('dailyBar') or {};prev=(row.get('prevDailyBar') or {}).get('c');price=trade.get('p') or bar.get('c')
            if not price:continue
            result.append(valid_quote({'symbol':symbol,'price':price,'currency':'USD','change_percent':(price/prev-1)*100 if prev else None,'high':bar.get('h'),'low':bar.get('l'),'volume':bar.get('v'),'as_of':trade.get('t') or bar.get('t'),'provider':'Alpaca · IEX only','period':'session'}))
        return {'quotes':result,'errors':[],'provider':'Alpaca · IEX only','fetched_at':stamp()}
    except (httpx.HTTPError,ValueError,KeyError,TypeError):
        raise HTTPException(503,'US stock data temporarily unavailable. Retry shortly.')
