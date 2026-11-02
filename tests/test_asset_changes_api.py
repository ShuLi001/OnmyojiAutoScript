"""Exercise the actual routes with an isolated repository; never start a device."""
import tempfile
import unittest
import asyncio
import json
from types import SimpleNamespace
from urllib.parse import urlencode, urlsplit
from unittest.mock import patch

from fastapi import FastAPI
from tasks.AssetSnapshot.history import SnapshotStore
from tests.test_asset_changes import MAPPING, payload


class AsgiClient:
    """Minimal in-process HTTP harness, requiring no additional test dependencies."""
    def __init__(self, app):
        self.app = app

    def get(self, url, params=None):
        return self.request('GET', url, params=params)

    def post(self, url, json=None):
        return self.request('POST', url, body=json)

    def request(self, method, url, params=None, body=None):
        async def run():
            parsed = urlsplit(url)
            messages = []
            encoded = json.dumps(body).encode() if body is not None else b''
            scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
                     'method': method, 'scheme': 'http', 'path': parsed.path, 'raw_path': parsed.path.encode(),
                     'query_string': (urlencode(params) if params else parsed.query).encode(),
                     'headers': [(b'content-type', b'application/json')],
                     'client': ('127.0.0.1', 123), 'server': ('test', 80), 'root_path': ''}
            async def receive():
                return {'type': 'http.request', 'body': encoded, 'more_body': False}
            async def send(message):
                messages.append(message)
            await self.app(scope, receive, send)
            start = next(m for m in messages if m['type'] == 'http.response.start')
            raw = b''.join(m.get('body', b'') for m in messages if m['type'] == 'http.response.body')
            return SimpleNamespace(status_code=start['status'],
                headers={k.decode(): v.decode() for k, v in start['headers']}, json=lambda: json.loads(raw))
        return asyncio.run(run())


class AssetChangesApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from module.server import script_router
        cls.router = script_router
        app = FastAPI()
        app.include_router(script_router.script_app)
        cls.client = AsgiClient(app)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SnapshotStore(self.temp.name, 'test', 'device', 'character', MAPPING)
        patcher = patch.object(self.router, 'asset_store', return_value=self.store)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_real_routes_capture_once_and_query_new_history_without_cache(self):
        first = self.store.save(payload('2026-11-01T12:00:00Z', 100), 'composite', None)
        second = self.store.save(payload('2026-11-02T12:00:00Z', 126), 'recent', first)
        result = self.client.get('/test/asset_snapshot')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers['cache-control'], 'no-store')
        self.assertEqual(result.json()['assets']['gold']['change']['delta'], 26)
        captured = self.client.post('/test/asset_snapshot/captures', json={'idempotencyKey': 'test-once-key'})
        self.assertEqual(captured.status_code, 202)
        again = self.client.post('/test/asset_snapshot/captures', json={'idempotencyKey': 'test-once-key'})
        self.assertEqual(captured.json()['requestId'], again.json()['requestId'])
        status = self.client.get(captured.json()['statusUrl'])
        self.assertEqual(status.json()['status'], 'queued')
        chart = self.client.get('/test/asset_snapshot/history', params={'asset': 'gold', 'report_date': '2026-11-02',
            'as_of_snapshot_id': second['snapshotId']})
        self.assertEqual(chart.status_code, 200)
        self.assertEqual(chart.json()['daily'][-1]['delta'], 26)
        self.assertEqual(chart.json()['window']['asOfSnapshotId'], second['snapshotId'])

    def test_validation_and_unknown_request(self):
        self.assertEqual(self.client.get('/test/asset_snapshot/history?asset=bad').status_code, 422)
        self.assertEqual(self.client.get('/test/asset_snapshot/history?asset=gold&days=400').status_code, 422)
        self.assertEqual(self.client.get('/test/asset_snapshot/history?asset=gold&as_of_snapshot_id=999').status_code, 404)
        self.assertEqual(self.client.get('/test/asset_snapshot/captures/unknown').status_code, 404)
        self.assertEqual(self.client.post('/test/asset_snapshot/captures', json={}).status_code, 422)


if __name__ == '__main__':
    unittest.main()
