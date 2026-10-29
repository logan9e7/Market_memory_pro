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
            return httpx.Response(200,request=httpx.Request('GET','https://data-api.binance.vision'),json=[{'symbol':'BTCUSDT','lastPrice':'100','priceChangePercent':'2','highPrice':'102','lowPrice':'97','volume':'42','closeTime':1793290000000}])
        with patch('app.api_discovery.httpx.AsyncClient.get',side_effect=provider) as call:
            result=self.client.get('/api/discovery/prices?symbols=BTCUSDT')
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json()['quotes'][0]['price'],100)
            self.client.get('/api/discovery/prices?symbols=BTCUSDT')
            self.assertEqual(call.call_count,1)
        with patch('app.api_discovery.httpx.AsyncClient.get',side_effect=httpx.ConnectError('offline')):
            self.assertEqual(self.client.get('/api/discovery/prices?symbols=ETHUSDT').status_code,503)
        self.assertEqual(self.client.get('/api/state').json()['quotes'],[])
