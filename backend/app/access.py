"""Single-workspace bearer access for local staging and gateway integrations."""
import hmac
import os
from dataclasses import dataclass, field
import re

from fastapi import Request
from fastapi.responses import JSONResponse

from .runtime_config import secret_setting

REVIEW_PATH = re.compile(r"^/api/runs/[^/]+/review$")
ROLES = ("viewer", "evaluator", "reviewer")


@dataclass(frozen=True)
class AccessConfig:
    tokens: dict[str, str] = field(repr=False)

    @classmethod
    def from_env(cls):
        mode = os.getenv("ERROR_DODGE_ACCESS_MODE", "demo")
        if mode == "demo":
            return cls({})
        if mode != "token":
            raise ValueError("Unsupported Error Dodge access mode")
        tokens = {role: secret_setting(f"ERROR_DODGE_{role.upper()}_TOKEN") for role in ROLES}
        if any(len(token) < 32 or not token.isascii() or any(char.isspace() for char in token)
               for token in tokens.values()) or len(set(tokens.values())) != len(ROLES):
            raise ValueError("Token mode requires three distinct ASCII tokens of at least 32 characters")
        return cls(tokens)

    def role(self, authorization: str) -> str | None:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() != "bearer" or not value.isascii() or len(value) > 2048:
            return None
        return next((role for role, token in self.tokens.items() if hmac.compare_digest(value, token)), None)


def install_access(app, config: AccessConfig) -> None:
    @app.middleware("http")
    async def authorize(request: Request, next_handler):
        path = request.url.path
        if path == "/api/access" or not path.startswith("/api/"):
            return await next_handler(request)
        role = config.role(request.headers.get("Authorization", "")) if config.tokens else "reviewer"
        if role is None:
            return JSONResponse({"detail": "Bearer credentials required"}, status_code=401,
                                headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"})
        method = request.method
        is_write = method not in {"GET", "HEAD", "OPTIONS"}
        route = path.rstrip("/")
        permitted_write = method == "POST" and (
            (route in {"/api/runs", "/api/evaluations"} and role in {"evaluator", "reviewer"})
            or (REVIEW_PATH.fullmatch(route) is not None and role == "reviewer")
        )
        if is_write and not permitted_write:
            return JSONResponse({"detail": "This role cannot perform that action"}, status_code=403,
                                headers={"Cache-Control": "no-store"})
        request.state.role = role
        response = await next_handler(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/api/access")
    def access_status():
        return {"authentication_required": bool(config.tokens)}

    @app.get("/api/session")
    def session(request: Request):
        return {"role": request.state.role}
