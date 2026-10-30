import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from app.main import create_app

class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(Path(self.temp.name)/'memory.db')
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.client.post('/api/register', json={'username':'discovery-user','password':'Strong-password123!'})

    def test_watchlist_is_private_idempotent_and_persistent(self):
        for _ in range(2):
            self.assertEqual(self.client.post('/api/discovery/watchlist',json={'symbol':'btcusdt'}).status_code,200)
        self.assertEqual(self.client.get('/api/discovery/watchlist').json()['symbols'],['BTCUSDT'])
        other = TestClient(self.app)
        self.addCleanup(other.close)
        self.assertEqual(other.get('/api/discovery/watchlist').status_code,401)
        other.post('/api/register',json={'username':'other-discovery','password':'Another-password123!'})
        self.assertEqual(other.get('/api/discovery/watchlist').json()['symbols'],[])
        other.delete('/api/discovery/watchlist/BTCUSDT')
        self.assertEqual(self.client.get('/api/discovery/watchlist').json()['symbols'],['BTCUSDT'])
        self.client.delete('/api/discovery/watchlist/BTCUSDT')
        self.assertEqual(self.client.get('/api/discovery/watchlist').json()['symbols'],[])

    def test_validation_and_capacity(self):
        self.assertEqual(self.client.get('/api/discovery/prices?symbols=bad/path').status_code,422)
        self.assertEqual(self.client.post('/api/discovery/watchlist',json={'symbol':'<script>'}).status_code,422)
        for i in range(20):
            self.assertEqual(self.client.post('/api/discovery/watchlist',json={'symbol':f'ASSET{i}USDT'}).status_code,200)
        self.assertEqual(self.client.post('/api/discovery/watchlist',json={'symbol':'EXTRAUSDT'}).status_code,409)

    def test_provider_prices_cache_and_failure(self):
        async def provider(*args,**kwargs):
            self.assertNotIn(' ', kwargs['params']['symbols'])
            return httpx.Response(200,request=httpx.Request('GET','https://data-api.binance.vision'),json=[{'symbol':'BTCUSDT','lastPrice':'100','priceChangePercent':'2','highPrice':'102','lowPrice':'97','volume':'42','closeTime':1793290000000}])
        with patch('app.api_discovery.httpx.AsyncClient.get',side_effect=provider) as call:
            result=self.client.get('/api/discovery/prices?symbols=BTCUSDT')
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json()['quotes'][0]['price'],100)
            self.client.get('/api/discovery/prices?symbols=BTCUSDT')
            self.assertEqual(call.call_count,1)
            self.assertEqual(self.client.get('/api/discovery/prices?symbols=BTCUSDT,ETHUSDT,SOLUSDT').status_code,200)
            self.assertEqual(call.call_args.kwargs['params']['symbols'], '["BTCUSDT","ETHUSDT","SOLUSDT"]')
        with patch('app.api_discovery.httpx.AsyncClient.get',side_effect=httpx.ConnectError('offline')):
            self.assertEqual(self.client.get('/api/discovery/prices?symbols=ETHUSDT').status_code,503)
        self.assertEqual(self.client.get('/api/state').json()['quotes'],[])

    def test_bare_crypto_ticker_is_normalized(self):
        async def provider(*args,**kwargs):
            self.assertEqual(kwargs['params']['symbols'],'["RAYUSDT"]')
            return httpx.Response(200,request=httpx.Request('GET','https://data-api.binance.vision'),json=[{'symbol':'RAYUSDT','lastPrice':'2','priceChangePercent':'1','highPrice':'3','lowPrice':'1','volume':'100','closeTime':1793290000000}])
        with patch('app.api_discovery.httpx.AsyncClient.get',side_effect=provider):
            response=self.client.get('/api/discovery/prices?symbols=RAY')
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['quotes'][0]['symbol'],'RAYUSDT')

    def test_exchange_outage_uses_labeled_same_currency_fallback(self):
        async def provider(url,**kwargs):
            if 'binance' in url:raise httpx.ConnectError('blocked')
            self.assertEqual(kwargs['params']['pair'],'XBTUSDT')
            return httpx.Response(200,request=httpx.Request('GET',url),json={'error':[],'result':{'XBTUSDT':{'c':['100','1'],'h':['101','102'],'l':['98','97'],'v':['1','2']}}})
        with patch('app.api_discovery.httpx.AsyncClient.get',side_effect=provider):
            response=self.client.get('/api/discovery/prices?symbols=BTCUSDT')
            self.assertEqual(response.status_code,200,response.text)
            q=response.json()['quotes'][0]
            self.assertEqual(q['currency'],'USDT')
            self.assertIn('Kraken',q['provider'])
            self.assertIsNone(q['change_percent'])
            self.assertEqual(q['timestamp_kind'],'retrieved')

    def test_stock_connections_fail_clearly_without_credentials(self):
        with patch.dict('os.environ',{},clear=True):
            for path,word in [('/api/discovery/quotes?market=us&symbols=AAPL','Alpaca'),('/api/discovery/search?market=india&q=RELIANCE','Upstox'),('/api/discovery/search?market=fo&q=NIFTY','Upstox')]:
                result=self.client.get(path)
                self.assertEqual(result.status_code,503,result.text)
                self.assertIn(word,result.json()['detail'])

    def test_multimarket_watchlists_keep_instrument_identity(self):
        for market,symbol in [('us','AAPL'),('india','NSE_EQ|INE002A01018'),('fo','NSE_FO|12345')]:
            self.assertEqual(self.client.post('/api/discovery/watchlist',json={'market':market,'symbol':symbol}).status_code,200)
        symbols=self.client.get('/api/discovery/watchlist').json()['symbols']
        self.assertIn('US:AAPL',symbols)
        self.assertIn('INDIA:NSE_EQ|INE002A01018',symbols)
        self.assertIn('FO:NSE_FO|12345',symbols)
        self.assertEqual(self.client.delete('/api/discovery/watchlist/FO:NSE_FO%7C12345').status_code,200)
        self.assertNotIn('FO:NSE_FO|12345',self.client.get('/api/discovery/watchlist').json()['symbols'])

    def test_stock_adapters_preserve_feed_and_trade_time(self):
        async def provider(url,**kwargs):
            if 'alpaca' in url:
                return httpx.Response(200,request=httpx.Request('GET',url),json={'AAPL':{'latestTrade':{'p':110,'t':'2026-10-29T14:00:00Z'},'dailyBar':{'h':111,'l':99,'v':100},'prevDailyBar':{'c':100}}})
            return httpx.Response(200,request=httpx.Request('GET',url),json={'status':'success','data':{'NSE_EQ:RELIANCE':{'symbol':'RELIANCE','instrument_token':'NSE_EQ|INE002A01018','last_price':110,'net_change':10,'last_trade_time':'1793290000000','ohlc':{'high':111,'low':99},'volume':100,'oi':0}}})
        with patch.dict('os.environ',{'ALPACA_API_KEY':'test','ALPACA_SECRET_KEY':'test','UPSTOX_ACCESS_TOKEN':'test'}),patch('app.api_discovery.httpx.AsyncClient.get',side_effect=provider):
            q=self.client.get('/api/discovery/quotes?market=us&symbols=AAPL').json()['quotes'][0]
            self.assertEqual(q['as_of'],'2026-10-29T14:00:00Z')
            self.assertIn('IEX',q['provider'])
            q=self.client.get('/api/discovery/quotes?market=india&symbols=NSE_EQ%7CINE002A01018').json()['quotes'][0]
            self.assertEqual(q['currency'],'INR')
            self.assertEqual(q['change_percent'],10)

    def test_capture_accepts_stablecoin_currency_and_contract_key(self):
        r=self.client.post('/api/quotes',json={'symbol':'BTCUSDT','price':100,'currency':'USDT'})
        self.assertEqual(r.status_code,201,r.text)
        r=self.client.post('/api/quotes',json={'symbol':'NSE_FO|12345','price':100,'currency':'INR'})
        self.assertEqual(r.status_code,201,r.text)

    def test_manual_capture_saves_price_and_note_together(self):
        result=self.client.post('/api/captures',json={'symbol':'BTCUSDT','currency':'USDT','price':123.45,'note':'Support retest; keep this moment.'})
        self.assertEqual(result.status_code,201,result.text)
        state=self.client.get('/api/state').json()
        self.assertEqual(len(state['quotes']),1)
        self.assertEqual(len(state['snapshots']),1)
        self.assertEqual(state['snapshots'][0]['quote_id'],result.json()['quote_id'])
        self.assertEqual(state['snapshots'][0]['price'],123.45)
        self.assertEqual(state['snapshots'][0]['note'],'Support retest; keep this moment.')
        other=TestClient(self.app)
        self.addCleanup(other.close)
        other.post('/api/register',json={'username':'capture-other','password':'Another-password123!'})
        self.assertEqual(other.get('/api/state').json()['snapshots'],[])

    def test_invalid_capture_cannot_leave_partial_price(self):
        result=self.client.post('/api/captures',json={'symbol':'BTCUSDT','currency':'USDT','price':123.45,'note':'x'*5001})
        self.assertEqual(result.status_code,422)
        state=self.client.get('/api/state').json()
        self.assertEqual(state['quotes'],[])
        self.assertEqual(state['snapshots'],[])
