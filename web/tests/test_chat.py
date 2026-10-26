import asyncio
import base64
import json
import logging
import unittest

import httpx
from starlette.testclient import TestClient

from chat import create_app

PASSWORD = "pa55word"
API_KEY = "vllm-s3cret-key"
CANARY = "canary-7f3a"
ENV = {
    "VLLM_URL": "http://vllm:8000",
    "VLLM_API_KEY": API_KEY,
    "SERVED_MODEL_NAME": "qwen-test",
    "CHAT_PASSWORD": PASSWORD,
    "CHAT_MAX_TOKENS": "100",
}
SSE = (
    b'data: {"model": "qwen-test", "choices": [{"delta": {"content": "answer ' + CANARY.encode() + b'"}}]}\n\n'
    b"data: [DONE]\n\n"
)


def basic(password, login="user"):
    return "Basic " + base64.b64encode(f"{login}:{password}".encode()).decode()


AUTH = {"Authorization": basic(PASSWORD)}
QUESTION = {"messages": [{"role": "user", "content": f"Repeat {CANARY}"}]}


class FakeVllm:
    def __init__(self, status=200, body=None, error=None):
        self.status = status
        self.body = body
        self.error = error
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        if self.status == 200:
            # content httpx вычитывает сразу, а настоящий ответ идёт потоком
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=httpx.ByteStream(SSE))
        return httpx.Response(self.status, json=self.body)


def client_for(vllm):
    return TestClient(create_app(ENV, transport=httpx.MockTransport(vllm)))


def post(vllm, body=QUESTION, headers=None):
    return client_for(vllm).post("/api/chat", json=body, headers={**AUTH, **(headers or {})})


class AuthTest(unittest.TestCase):
    def setUp(self):
        self.client = client_for(FakeVllm())

    def test_healthz_is_open(self):
        self.assertEqual(self.client.get("/healthz").status_code, 200)

    def test_page_needs_password(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 401)
        self.assertIn("Basic", response.headers["www-authenticate"])

    def test_wrong_password(self):
        self.assertEqual(self.client.get("/", headers={"Authorization": basic("nope")}).status_code, 401)

    def test_bearer_is_not_basic(self):
        response = self.client.get("/", headers={"Authorization": f"Bearer {PASSWORD}"})
        self.assertEqual(response.status_code, 401)

    def test_broken_header(self):
        self.assertEqual(self.client.get("/", headers={"Authorization": "Basic !!!"}).status_code, 401)

    def test_any_login(self):
        response = self.client.get("/", headers={"Authorization": basic(PASSWORD, "someone")})
        self.assertEqual(response.status_code, 200)

    def test_api_needs_password(self):
        self.assertEqual(self.client.post("/api/chat", json=QUESTION).status_code, 401)

    def test_security_headers(self):
        response = self.client.get("/", headers=AUTH)
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")

    def test_empty_password_refused(self):
        with self.assertRaises(RuntimeError):
            create_app({**ENV, "CHAT_PASSWORD": ""})


class ChatTest(unittest.TestCase):
    def test_request_to_vllm(self):
        vllm = FakeVllm()
        body = {
            "model": "other",
            "n": 5,
            "logprobs": True,
            "max_tokens": 5000,
            "messages": [
                {"role": "system", "content": "s", "name": "x"},
                {"role": "user", "content": "q"},
            ],
        }
        self.assertEqual(post(vllm, body).status_code, 200)
        request = vllm.requests[0]
        self.assertEqual(request.url.path, "/v1/chat/completions")
        self.assertEqual(request.headers["authorization"], f"Bearer {API_KEY}")
        self.assertEqual(json.loads(request.content), {
            "model": "qwen-test",
            "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}],
            "temperature": 0.7,
            "max_tokens": 100,
            "stream": True,
            "stream_options": {"include_usage": True},
        })

    def test_stream_passes_through(self):
        response = post(FakeVllm())
        self.assertEqual(response.content, SSE)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_form_content_type_refused(self):
        vllm = FakeVllm()
        response = client_for(vllm).post(
            "/api/chat", content=json.dumps(QUESTION),
            headers={**AUTH, "Content-Type": "text/plain"},
        )
        self.assertEqual(response.status_code, 415)
        self.assertEqual(vllm.requests, [])

    def test_cross_site_refused(self):
        self.assertEqual(post(FakeVllm(), headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
        self.assertEqual(post(FakeVllm(), headers={"Sec-Fetch-Site": "same-site"}).status_code, 403)
        self.assertEqual(post(FakeVllm(), headers={"Sec-Fetch-Site": "same-origin"}).status_code, 200)

    def test_body_too_large(self):
        body = {"messages": [{"role": "user", "content": "x" * 300_000}]}
        self.assertEqual(post(FakeVllm(), body).status_code, 413)

    def test_bad_requests(self):
        for body in (
            {},
            {"messages": []},
            {"messages": [{"role": "tool", "content": "x"}]},
            {"messages": [{"role": "user", "content": ["x"]}]},
            {"messages": [{"role": "user", "content": "x"}], "temperature": 5},
            {"messages": [{"role": "user", "content": "x"}], "max_tokens": "10"},
            [1, 2],
        ):
            with self.subTest(body=body):
                self.assertEqual(post(FakeVllm(), body).status_code, 400)

    def test_not_json(self):
        response = client_for(FakeVllm()).post(
            "/api/chat", content=b"{oops", headers={**AUTH, "Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 400)

    def test_vllm_client_error_passes_through(self):
        response = post(FakeVllm(400, {"error": {"message": "context is too long"}}))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["message"], "context is too long")

    def test_vllm_auth_error_is_502(self):
        self.assertEqual(post(FakeVllm(401, {"error": "Unauthorized"})).status_code, 502)

    def test_vllm_down_is_502(self):
        self.assertEqual(post(FakeVllm(error=httpx.ConnectError("refused"))).status_code, 502)

    def test_pool_busy_is_429(self):
        self.assertEqual(post(FakeVllm(error=httpx.PoolTimeout("busy"))).status_code, 429)

    def test_token_never_reaches_browser(self):
        responses = [
            client_for(FakeVllm()).get(path, headers=AUTH) for path in ("/", "/chat.js", "/chat.css")
        ]
        responses += [
            post(FakeVllm()),
            post(FakeVllm(), {"messages": []}),
            post(FakeVllm(401, {"error": "Unauthorized"})),
            post(FakeVllm(error=httpx.ConnectError("refused"))),
        ]
        for response in responses:
            self.assertNotIn(API_KEY, response.text)
            self.assertNotIn(API_KEY, str(response.headers))


class Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(self.format(record))


class LoggingTest(unittest.TestCase):
    def test_no_prompts_or_answers_in_logs(self):
        capture = Capture()
        root = logging.getLogger()
        old_level = root.level
        root.addHandler(capture)
        root.setLevel(logging.DEBUG)
        self.addCleanup(root.removeHandler, capture)
        self.addCleanup(root.setLevel, old_level)

        self.assertEqual(post(FakeVllm()).status_code, 200)
        post(FakeVllm(400, {"error": {"message": f"bad {CANARY}"}}))
        post(FakeVllm(error=httpx.ConnectError("refused")))
        post(FakeVllm(), {"messages": [{"role": CANARY, "content": CANARY}]})

        self.assertTrue(capture.lines)
        for line in capture.lines:
            self.assertNotIn(CANARY, line)
            self.assertNotIn(API_KEY, line)


class HangingStream(httpx.AsyncByteStream):
    """первый чанк сразу, дальше vllm будто думает над следующим токеном"""

    def __init__(self):
        self.closed = False

    async def __aiter__(self):
        yield SSE.split(b"\n\n")[0] + b"\n\n"
        await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


class DisconnectTest(unittest.TestCase):
    def test_client_disconnect_closes_vllm_stream(self):
        stream = HangingStream()
        app = create_app(ENV, transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)
        ))
        body = json.dumps(QUESTION).encode()
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/chat",
            "raw_path": b"/api/chat",
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"authorization", AUTH["Authorization"].encode()),
                (b"content-type", b"application/json"),
            ],
            "client": ("127.0.0.1", 50000),
            "server": ("chat", 8080),
        }

        async def run():
            got_chunk = asyncio.Event()
            sent = []
            messages = [{"type": "http.request", "body": body, "more_body": False}]

            async def receive():
                if messages:
                    return messages.pop()
                # браузер закрыл вкладку или нажал "Стоп" после первого токена
                await got_chunk.wait()
                return {"type": "http.disconnect"}

            async def send(message):
                sent.append(message)
                if message.get("body"):
                    got_chunk.set()

            await asyncio.wait_for(app(scope, receive, send), timeout=5)
            return sent

        sent = asyncio.run(run())
        self.assertEqual(sent[0]["status"], 200)
        self.assertTrue(stream.closed)


if __name__ == "__main__":
    unittest.main()
