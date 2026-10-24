import asyncio
import os
import unittest
from unittest import mock

from vllm_guard.auth import BearerAuth

TOKEN = "s3cret"


async def app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def call(path, authorization=None, scope_type="http"):
    headers = [(b"authorization", authorization.encode())] if authorization else []
    scope = {"type": scope_type, "path": path, "headers": headers}
    sent = []

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        sent.append(message)

    with mock.patch.dict(os.environ, {"VLLM_API_KEY": TOKEN}):
        middleware = BearerAuth(app)
    asyncio.run(middleware(scope, receive, send))
    return sent[0]


def status(path, authorization=None):
    return call(path, authorization)["status"]


class BearerAuthTest(unittest.TestCase):
    def test_invocations_closed_without_token(self):
        self.assertEqual(status("/invocations"), 401)

    def test_wrong_token(self):
        self.assertEqual(status("/v1/chat/completions", "Bearer nope"), 401)

    def test_wrong_scheme(self):
        self.assertEqual(status("/v1/chat/completions", f"Basic {TOKEN}"), 401)

    def test_valid_token(self):
        self.assertEqual(status("/v1/chat/completions", f"Bearer {TOKEN}"), 200)
        self.assertEqual(status("/invocations", f"bearer {TOKEN}"), 200)

    def test_health_is_open(self):
        self.assertEqual(status("/health"), 200)

    def test_websocket_closed_without_token(self):
        message = call("/v1/realtime", scope_type="websocket")
        self.assertEqual(message, {"type": "websocket.close", "code": 1008})

    def test_missing_token_env(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                BearerAuth(app)


if __name__ == "__main__":
    unittest.main()
