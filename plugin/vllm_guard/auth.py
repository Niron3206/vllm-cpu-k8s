"""ASGI-middleware

Ввстроенный --api-key в vllm проверяет только префиксы /v1, /v2, /inference и /cohere
При этом /invocations отдаёт ту же генерацию без всякого токена
Здесь наоборот: закрыто всё, кроме явно открытого

Подключение: --middleware vllm_guard.auth.BearerAuth, токен из VLLM_API_KEY
"""

import hashlib
import hmac
import os

OPEN_PATHS = {"/health"}

_UNAUTHORIZED = b'{"error": "Unauthorized"}'

def _sha256(value):
    return hashlib.sha256(value.encode()).digest()

class BearerAuth:
    def __init__(self, app):
        token = os.environ.get("VLLM_API_KEY")
        if not token:
            raise RuntimeError("VLLM_API_KEY не задан")
        self.app = app
        self.token_hash = _sha256(token)

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket") or self._allowed(scope):
            await self.app(scope, receive, send)
        elif scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
        else:
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(_UNAUTHORIZED)).encode()),
                    (b"www-authenticate", b"Bearer"),
                ],
            })
            await send({"type": "http.response.body", "body": _UNAUTHORIZED})

    def _allowed(self, scope):
        path = scope["path"].removeprefix(scope.get("root_path", ""))
        
        if path in OPEN_PATHS:
            return True
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                scheme, _, token = value.decode("latin-1").partition(" ")
                return scheme.lower() == "bearer" and hmac.compare_digest(
                    _sha256(token), self.token_hash
                )
        return False
