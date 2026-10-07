"""The account backend and token issuer of the `account/read` recovery lane, faked.

M8-N5-account-read-recovery.md: one HTTPS server at production's port serves
both ``chatgpt.com`` and ``auth.openai.com``, choosing its certificate by SNI
from the trust fixture's throwaway CA, so the pinned client runs production's
configuration and URLs unchanged. Every token is a fixture; the log names a
token only by its class, so no evidence or failure message carries one.
"""

from __future__ import annotations

import base64
import json
import socket
import ssl
import threading
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

BACKEND, ISSUER = "chatgpt.com", "auth.openai.com"
LEAVES = {BACKEND: "backend", ISSUER: "issuer"}
"""The trust fixture's leaf for each host (``scripts/ci/build_m8_trust_fixture.py``)."""

CHECK = "/backend-api/wham/accounts/check"
USAGE = "/backend-api/wham/usage"
RESET_CREDITS = "/backend-api/wham/rate-limit-reset-credits"
TOKEN = "/oauth/token"

ACCOUNT_ID, USER_ID, OTHER_USER_ID = "acct-fixture", "user-fixture", "user-other"
CASES = ("clean", "refused", "unauthorized", "bounded", "changed", "unsealed")
"""``bounded`` answers as ``unauthorized`` does, under a smaller egress bound."""


def _segment(value: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()


def jwt(claims: dict[str, Any]) -> str:
    """An unsigned fixture JWT: the pin parses claims without a signature check
    (``login/src/token_data.rs:129-198``)."""

    return f"{_segment({'alg': 'none', 'typ': 'JWT'})}.{_segment(claims)}.fixture"


EXPIRY = int((datetime.now(UTC) + timedelta(days=30)).timestamp())
"""One expiry for every fixture token, far beyond the pin's five-minute
proactive-refresh window, so a generation's token is the same string each time."""


def id_token(user: str = USER_ID) -> str:
    return jwt({"email": "fixture@example.invalid", "exp": EXPIRY,
                "https://api.openai.com/auth": {
                    "chatgpt_plan_type": "pro", "chatgpt_user_id": user,
                    "chatgpt_account_id": ACCOUNT_ID}})


@dataclass(frozen=True)
class Tokens:
    """One generation's fixture tokens; ``access`` is a JWT with a far ``exp``."""

    generation: str
    user: str = USER_ID

    @property
    def access(self) -> str:
        return jwt({"exp": EXPIRY, "jti": f"access-{self.generation}"})

    @property
    def refresh(self) -> str:
        return f"refresh-{self.generation}"


OLD, NEW, OTHER = Tokens("old"), Tokens("new"), Tokens("other", OTHER_USER_ID)


def fixture_tokens() -> list[str]:
    """Every token the fakes or the credential carry, id tokens included: none may
    appear in evidence."""

    return [id_token(USER_ID), id_token(OTHER_USER_ID)] + [
        getattr(tokens, kind) for tokens in (OLD, NEW, OTHER) for kind in ("access", "refresh")]


def credential() -> bytes:
    """The store's fixture ``auth.json``: the pin's minimal ChatGPT shape, with the
    ``tokens.account_id`` and recent ``last_refresh`` the check requires."""

    return json.dumps({
        "auth_mode": "chatgpt", "OPENAI_API_KEY": None,
        "tokens": {"id_token": id_token(), "access_token": OLD.access,
                   "refresh_token": OLD.refresh, "account_id": ACCOUNT_ID},
        "last_refresh": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }).encode()


def classify(value: str | None, field_name: str) -> str | None:
    """A token's class, never its value: ``old``, ``new``, ``other`` or ``unknown``."""

    if value is None:
        return None
    for tokens in (OLD, NEW, OTHER):
        if value == getattr(tokens, field_name):
            return tokens.generation
    return "unknown"


def _account(origin: str) -> dict[str, Any]:
    return {"accounts": [{"id": ACCOUNT_ID, "workspace_backend_origin": origin,
                          "account_routing_override": "NO_CONSTRAINT", "plan_type": "pro"}],
            "default_account_id": ACCOUNT_ID}


@dataclass
class Script:
    """What the fakes answer in one case, and the ordered log of what they were asked."""

    case: str
    log: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.case not in CASES:
            raise ValueError(f"unknown recovery case {self.case!r}")

    def respond(self, host: str, method: str, path: str, headers: dict[str, str],
                body: bytes) -> tuple[int, Any]:
        bearer = headers.get("authorization", "")
        account = headers.get("chatgpt-account-id")
        entry: dict[str, Any] = {
            "host": host, "method": method, "path": path,
            "bearer": classify(bearer.removeprefix("Bearer ") if bearer else None, "access"),
            # Classified like a token: a value is never copied into the log.
            "account": None if account is None else (
                "fixture" if account == ACCOUNT_ID else "other"),
        }
        status, answer = self._answer(host, method, path, entry, body)
        entry["status"] = status
        self.log.append(entry)
        return status, answer

    def _answer(self, host: str, method: str, path: str, entry: dict[str, Any],
                body: bytes) -> tuple[int, Any]:
        if (host, method, path) == (ISSUER, "POST", TOKEN):
            try:
                request = json.loads(body)
            except ValueError:
                request = None
            token = request.get("refresh_token") if isinstance(request, dict) else None
            entry["refresh_token"] = classify(token if isinstance(token, str) else None, "refresh")
            entry["grant"] = isinstance(request, dict) and (
                request.get("grant_type") == "refresh_token")
            if not entry["grant"] or entry["refresh_token"] is None:
                return 400, {"error": "invalid_request"}
            if self.case == "refused":
                return 401, {"error": "invalid_grant"}
            issued = OTHER if self.case == "changed" else NEW
            return 200, {"id_token": id_token(issued.user), "access_token": issued.access,
                         "refresh_token": issued.refresh}
        if host != BACKEND or method != "GET":
            return 404, None
        fresh = entry["bearer"] in ("new", "other") and entry["account"] == "fixture"
        if path == CHECK:
            if not fresh or self.case in ("unauthorized", "bounded"):
                return 401, {"detail": "fixture unauthorized"}
            origin = "https://elsewhere.invalid" if self.case == "unsealed" else "https://chatgpt.com"
            return 200, _account(origin)
        if path == USAGE:
            return (200, {"plan_type": "pro"}) if fresh else (401, None)
        return 404, None


class AccountPeer:
    """The fake ``chatgpt.com`` and ``auth.openai.com`` at ``127.0.0.1:443``.

    Each session records its SNI and, only once its whole answer is sent,
    ``answered``; otherwise the TLS alert the client sent or the error that ended
    it. Any failure is recorded, never swallowed, so a reset, a deadline, a
    truncated request or a fault in the fake can never pass as an answer.
    """

    def __init__(self, case: str, pki: Path, *, port: int = 443) -> None:
        self.script = Script(case)
        self.contexts = {}
        for host, leaf in LEAVES.items():
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(pki / f"{leaf}.pem", pki / f"{leaf}.key")
            self.contexts[host] = context
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.sni_callback = self._select
        self.server = socket.create_server(("127.0.0.1", port))
        self.sessions: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        threading.Thread(target=self._serve, daemon=True).start()

    def _select(self, tls: ssl.SSLSocket, name: str | None, _context: ssl.SSLContext) -> Any:
        """The SNI callback: a server socket keeps no ``server_hostname``, so the
        name the client sent is recorded here, on its socket."""
        if name not in self.contexts:
            return ssl.ALERT_DESCRIPTION_UNRECOGNIZED_NAME
        tls.context = self.contexts[name]
        tls.fixture_sni = name  # type: ignore[attr-defined]
        return None

    def _serve(self) -> None:
        while True:
            try:
                raw, _ = self.server.accept()
            except OSError:
                return
            session: dict[str, Any] = {"done": False, "answered": False, "sni": None,
                                       "alert": None, "error": None}
            self.sessions.append(session)
            threading.Thread(target=self._session, args=(raw, session), daemon=True).start()

    def _session(self, raw: socket.socket, session: dict[str, Any]) -> None:
        try:
            with self.context.wrap_socket(raw, server_side=True) as tls:
                session["sni"] = getattr(tls, "fixture_sni", None)
                head = b""
                while b"\r\n\r\n" not in head and (chunk := tls.recv(8192)):
                    head += chunk
                header, _, body = head.partition(b"\r\n\r\n")
                line, *fields = header.decode("latin-1").split("\r\n")
                method, path, _ = line.split(" ", 2)
                headers = {}
                for item in fields:
                    name, _, value = item.partition(":")
                    headers[name.strip().lower()] = value.strip()
                length = int(headers.get("content-length", "0"))
                while len(body) < length and (chunk := tls.recv(8192)):
                    body += chunk
                if len(body) != length:
                    raise ValueError("the request body is not its declared length")
                host = headers.get("host", "").split(":", 1)[0]
                if host != session["sni"]:
                    raise ValueError("the request's host is not the session's name")
                with self.lock:
                    status, answer = self.script.respond(host, method, path, headers, body)
                payload = b"" if answer is None else json.dumps(answer).encode()
                tls.sendall(
                    f"HTTP/1.1 {status} Fixture\r\nContent-Type: application/json\r\n"
                    f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode()
                    + payload)
                session["answered"] = True
        except ssl.SSLError as exc:
            session["alert"] = exc.reason
        except Exception as exc:
            session["error"] = type(exc).__name__
        finally:
            raw.close()
            session["done"] = True

    @property
    def log(self) -> list[dict[str, Any]]:
        return self.script.log

    def close(self) -> None:
        """Release the port now: on Linux, closing a listener does not wake an
        ``accept`` blocked in another thread, which keeps it bound; a shutdown does."""
        with suppress(OSError):
            self.server.shutdown(socket.SHUT_RDWR)
        self.server.close()
