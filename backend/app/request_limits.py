"""Bound JSON API payloads before FastAPI reads them."""
from starlette.responses import JSONResponse


class RequestBodyLimit:
    def __init__(self, app, max_bytes=16_384):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH", "DELETE"}
                or not scope["path"].startswith("/api/")):
            await self.app(scope, receive, send)
            return

        total = 0
        chunks = []
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self.max_bytes:
                await JSONResponse({"detail": "Request body too large"}, status_code=413,
                                   headers={"Cache-Control": "no-store"})(scope, receive, send)
                return
            if chunk:
                chunks.append(chunk)
            if not message.get("more_body", False):
                break

        async def replay():
            nonlocal chunks
            if chunks is not None:
                body = b"".join(chunks)
                chunks = None
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
