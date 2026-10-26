"""веб-чат с моделью, страница и прокси к vllm со стримингом

Токен vllm остаётся здесь, браузер его не видит. Вход по паролю (HTTP Basic,
логин любой). Тексты запросов и ответов приложение никуда не пишет

Запуск: uvicorn chat:create_app --factory
"""

import base64
import binascii
import contextlib
import hashlib
import hmac
import json
import os
from pathlib import Path

import httpx
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.middleware import Middleware
from starlette.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

STATIC = Path(__file__).parent / "static"
OPEN_PATHS = {"/healthz"}
ROLES = {"system", "user", "assistant"}
MAX_BODY = 256 * 1024
# больше одновременных стримов пул httpx не откроет, лишние получат 429
MAX_STREAMS = 8

SECURITY_HEADERS = [
    (b"content-security-policy",
     b"default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
]

_UNAUTHORIZED = b'{"error": "Unauthorized"}'


def _sha256(value):
    return hashlib.sha256(value.encode()).digest()


def _required(env, name):
    value = env.get(name)
    if not value:
        raise RuntimeError(f"{name} не задан")
    return value


def _with_headers(send):
    async def wrapped(message):
        if message["type"] == "http.response.start":
            message["headers"] = [*message.get("headers", []), *SECURITY_HEADERS]
        await send(message)
    return wrapped


class Guard:
    """пароль на всём, кроме OPEN_PATHS, и заголовки безопасности на каждом ответе"""

    def __init__(self, app, password):
        self.app = app
        self.password_hash = _sha256(password)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
        elif scope["type"] != "http":
            await send({"type": "websocket.close", "code": 1008})
        elif scope["path"] in OPEN_PATHS or self._allowed(scope):
            await self.app(scope, receive, _with_headers(send))
        else:
            send = _with_headers(send)
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(_UNAUTHORIZED)).encode()),
                    (b"www-authenticate", b'Basic realm="chat", charset="UTF-8"'),
                ],
            })
            await send({"type": "http.response.body", "body": _UNAUTHORIZED})

    def _allowed(self, scope):
        for name, value in scope["headers"]:
            if name == b"authorization":
                scheme, _, credentials = value.partition(b" ")
                if scheme.lower() != b"basic":
                    return False
                try:
                    decoded = base64.b64decode(credentials, validate=True).decode()
                except (binascii.Error, UnicodeDecodeError):
                    return False
                # логин не проверяем, пароль длинный и случайный
                password = decoded.partition(":")[2]
                return hmac.compare_digest(_sha256(password), self.password_hash)
        return False


def build_payload(data, model, max_tokens):
    """тело для vllm собирается из разрешённых полей, остальное отбрасывается"""
    messages = data.get("messages") if isinstance(data, dict) else None
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages")
    for message in messages:
        if (not isinstance(message, dict) or message.get("role") not in ROLES
                or not isinstance(message.get("content"), str)):
            raise ValueError("messages")

    temperature = data.get("temperature", 0.7)
    if isinstance(temperature, bool) or not isinstance(temperature, int | float) or not 0 <= temperature <= 2:
        raise ValueError("temperature")
    tokens = data.get("max_tokens", max_tokens)
    if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 1:
        raise ValueError("max_tokens")

    return {
        "model": model,
        "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        "temperature": temperature,
        "max_tokens": min(tokens, max_tokens),
        "stream": True,
        "stream_options": {"include_usage": True},
    }


def _error(status, text):
    return JSONResponse({"error": text}, status, headers={"Cache-Control": "no-store"})


async def _read_body(request, limit):
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            return None
    return bytes(body)


def create_app(env=os.environ, transport=None):
    model = _required(env, "SERVED_MODEL_NAME")
    password = _required(env, "CHAT_PASSWORD")
    max_tokens = int(env.get("CHAT_MAX_TOKENS", "1024"))
    client = httpx.AsyncClient(
        base_url=_required(env, "VLLM_URL"),
        headers={"Authorization": f"Bearer {_required(env, 'VLLM_API_KEY')}"},
        # под нагрузкой первый токен приходил через 200 с
        timeout=httpx.Timeout(5, read=600),
        limits=httpx.Limits(max_connections=MAX_STREAMS),
        transport=transport,
    )

    async def chat(request):
        content_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
        if content_type != "application/json":
            return _error(415, "нужен application/json")
        if request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
            return _error(403, "запрос с чужого сайта")

        body = await _read_body(request, MAX_BODY)
        if body is None:
            return _error(413, "слишком длинный запрос")
        try:
            payload = build_payload(json.loads(body), model, max_tokens)
        except ValueError as e:
            return _error(400, f"некорректный запрос: {e}")

        try:
            upstream = await client.send(
                client.build_request("POST", "/v1/chat/completions", json=payload), stream=True
            )
        except httpx.PoolTimeout:
            return _error(429, "слишком много одновременных запросов")
        except httpx.HTTPError:
            return _error(502, "модель недоступна")

        if upstream.status_code != 200:
            detail = await upstream.aread()
            if upstream.status_code in (401, 403) or upstream.status_code >= 500:
                return _error(502, f"vllm ответил {upstream.status_code}")
            # ошибка про запрос пользователя, отдаём ему как есть, но не логируем
            return Response(detail, upstream.status_code, media_type="application/json",
                            headers={"Cache-Control": "no-store"})

        # при обрыве клиента Starlette отменяет стрим, соединение с vllm закрывается и vllm снимает запрос с батча
        return StreamingResponse(
            upstream.aiter_raw(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
            background=BackgroundTask(upstream.aclose),
        )

    async def healthz(request):
        return PlainTextResponse("ok")

    @contextlib.asynccontextmanager
    async def lifespan(app):
        yield
        await client.aclose()

    return Starlette(
        routes=[
            Route("/healthz", healthz),
            Route("/api/chat", chat, methods=["POST"]),
            Mount("/", StaticFiles(directory=STATIC, html=True)),
        ],
        middleware=[Middleware(Guard, password=password)],
        lifespan=lifespan,
    )
