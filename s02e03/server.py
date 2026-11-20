# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp==2.3.0", "httpx>=0.27", "uvicorn>=0.30", "faster-whisper==1.2.1", "av>=15,<19"]
# ///
# av stays below 19: av 19 dropped the metadata_errors argument that faster-whisper 1.2.1 passes to av.open.
"""mcp-home: a remote MCP server with memo, upload and transcribe tools.

Two listeners:
  PUBLIC_PORT  - MCP endpoint, OAuth server, plan page, uploaded files. Published by Tailscale Funnel.
  CONSENT_PORT - the owner's approve/deny page. Published by `tailscale serve`, so tailnet only;
                 Tailscale's identity header says who is looking.
"""

import base64
import hashlib
import html
import ipaddress
import json
import logging
import mimetypes
import os
import re
import secrets
import socket
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

import anyio
import httpx
import uvicorn
from pydantic import AnyHttpUrl, BaseModel, Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from mcp.types import CallToolResult, TextContent

PUBLIC_URL = os.environ["PUBLIC_URL"].rstrip("/")
CONSENT_URL = os.environ["CONSENT_URL"].rstrip("/")
OWNER_LOGINS = {s.strip().lower() for s in os.environ["OWNER_LOGINS"].split(",") if s.strip()}
PUBLIC_PORT = int(os.environ.get("PUBLIC_PORT", "8765"))
CONSENT_PORT = int(os.environ.get("CONSENT_PORT", "8766"))
DATA_DIR = Path(os.path.expanduser(os.environ.get("DATA_DIR", "~/mcp-home/data")))
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")

RESOURCE = f"{PUBLIC_URL}/mcp"
SCOPE = "mcp"
ACCESS_TTL = 3600
REFRESH_TTL = 30 * 86400
CODE_TTL = 300
PENDING_TTL = 900
MAX_UPLOAD = 25 * 1024 * 1024
MAX_AUDIO = 100 * 1024 * 1024
MAX_MEMO = 20_000

log = logging.getLogger("mcp-home")
DATA_DIR.mkdir(parents=True, exist_ok=True)
FILES_DIR = DATA_DIR / "files"
FILES_DIR.mkdir(exist_ok=True)


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DATA_DIR / "mcp-home.db")
    conn.row_factory = sqlite3.Row
    return conn


with db() as c:
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS clients (client_id TEXT PRIMARY KEY, info TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS pending (id TEXT PRIMARY KEY, client_id TEXT NOT NULL, params TEXT NOT NULL,
            csrf TEXT, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS codes (code TEXT PRIMARY KEY, data TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS tokens (hash TEXT PRIMARY KEY, kind TEXT NOT NULL, client_id TEXT NOT NULL,
            scopes TEXT NOT NULL, resource TEXT, subject TEXT, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS memos (id TEXT PRIMARY KEY, text TEXT NOT NULL, client_id TEXT NOT NULL,
            client_name TEXT, created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS uploads (id TEXT PRIMARY KEY, filename TEXT NOT NULL, content_type TEXT NOT NULL,
            size INTEGER NOT NULL, client_id TEXT NOT NULL, created_at REAL NOT NULL);
        """
    )


def _hash(token: str) -> str:
    # Only hashes are stored, so a copy of the database cannot be replayed as tokens.
    return hashlib.sha256(token.encode()).hexdigest()


def _public_host(host: str) -> bool:
    # fred sits on the tailnet, so a fetched URL must not reach private or local addresses.
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    return bool(infos) and all(ipaddress.ip_address(i[4][0]).is_global for i in infos)


async def safe_get(url: str, limit: int, max_redirects: int = 5) -> tuple[bytes, str]:
    """GET a public https/http URL, re-checking every redirect hop against private addresses."""
    current = url
    async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
        for _ in range(max_redirects + 1):
            p = urlparse(current)
            if p.scheme not in ("http", "https") or not p.hostname or not _public_host(p.hostname):
                raise ToolError(f"{url}: not a public http(s) address, so it was not fetched")
            async with client.stream("GET", current) as r:
                if r.is_redirect:
                    current = str(r.url.join(r.headers["location"]))
                    continue
                if r.status_code >= 400:
                    raise ToolError(f"{url}: the server answered HTTP {r.status_code} {r.reason_phrase}".rstrip())
                chunks, total = [], 0
                async for chunk in r.aiter_bytes():
                    total += len(chunk)
                    if total > limit:
                        raise ToolError(f"{url}: larger than the {limit // (1024 * 1024)} MB limit")
                    chunks.append(chunk)
                return b"".join(chunks), r.headers.get("content-type", "")
    raise ToolError(f"{url}: more than {max_redirects} redirects")


# ---------------------------------------------------------------- OAuth provider


class Provider:
    """Authorization server for this one resource. Clients register (DCR) or bring a
    Client ID Metadata Document; every authorization waits for the owner's approval."""

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        with db() as c:
            row = c.execute("SELECT info, created FROM clients WHERE client_id=?", (client_id,)).fetchone()
        if row and not (client_id.startswith("https://") and time.time() - row["created"] > 3600):
            return OAuthClientInformationFull.model_validate_json(row["info"])
        if client_id.startswith("https://"):
            return await self._fetch_cimd(client_id)
        return None

    async def _fetch_cimd(self, client_id: str) -> OAuthClientInformationFull | None:
        if not urlparse(client_id).path.strip("/"):
            return None
        try:
            body, _ = await safe_get(client_id, 64 * 1024, max_redirects=0)
            doc = json.loads(body)
        except Exception as e:  # noqa: BLE001 - any fetch or parse failure means "unknown client"
            log.warning("client metadata fetch failed for %s: %s", client_id, e)
            return None
        if doc.get("client_id") != client_id or not doc.get("redirect_uris"):
            log.warning("client metadata at %s does not name itself or has no redirect_uris", client_id)
            return None
        info = OAuthClientInformationFull(
            client_id=client_id,
            client_name=doc.get("client_name"),
            client_uri=doc.get("client_uri"),
            redirect_uris=doc["redirect_uris"],
            grant_types=doc.get("grant_types") or ["authorization_code", "refresh_token"],
            response_types=["code"],
            token_endpoint_auth_method="none",
            # A metadata document names the client, not this server's scopes; the client asks for `mcp`
            # because our metadata says so, and the SDK refuses any scope the client record lacks.
            scope=SCOPE,
        )
        with db() as c:
            c.execute(
                "INSERT OR REPLACE INTO clients VALUES (?,?,?)", (client_id, info.model_dump_json(), time.time())
            )
        return info

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        with db() as c:
            c.execute(
                "INSERT OR REPLACE INTO clients VALUES (?,?,?)",
                (client_info.client_id, client_info.model_dump_json(), time.time()),
            )

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if params.resource and params.resource.rstrip("/") != RESOURCE:
            raise AuthorizeError("invalid_target", f"this server only issues tokens for {RESOURCE}")
        req_id = secrets.token_urlsafe(24)
        with db() as c:
            c.execute("DELETE FROM pending WHERE expires < ?", (time.time(),))
            c.execute(
                "INSERT INTO pending (id, client_id, params, expires) VALUES (?,?,?,?)",
                (req_id, client.client_id, params.model_dump_json(), time.time() + PENDING_TTL),
            )
        return f"{CONSENT_URL}/consent?req={req_id}"

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str):
        with db() as c:
            row = c.execute("SELECT data, expires FROM codes WHERE code=?", (_hash(authorization_code),)).fetchone()
        if not row or row["expires"] < time.time():
            return None
        code = AuthorizationCode.model_validate_json(row["data"])
        return code if code.client_id == client.client_id else None

    def _issue(self, client_id: str, scopes: list[str], subject: str | None) -> OAuthToken:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = time.time()
        with db() as c:
            c.execute("DELETE FROM tokens WHERE expires < ?", (now,))
            for tok, kind, ttl in ((access, "access", ACCESS_TTL), (refresh, "refresh", REFRESH_TTL)):
                c.execute(
                    "INSERT INTO tokens VALUES (?,?,?,?,?,?,?)",
                    (_hash(tok), kind, client_id, " ".join(scopes), RESOURCE, subject, now + ttl),
                )
        return OAuthToken(
            access_token=access, token_type="Bearer", expires_in=ACCESS_TTL, scope=" ".join(scopes),
            refresh_token=refresh,
        )

    async def exchange_authorization_code(self, client, authorization_code: AuthorizationCode) -> OAuthToken:
        with db() as c:
            # Single use: the code row goes before the tokens exist.
            deleted = c.execute("DELETE FROM codes WHERE code=?", (_hash(authorization_code.code),)).rowcount
        if not deleted:
            raise TokenError("invalid_grant", "authorization code already used")
        return self._issue(client.client_id, authorization_code.scopes, authorization_code.subject)

    async def load_refresh_token(self, client, refresh_token: str) -> RefreshToken | None:
        with db() as c:
            row = c.execute(
                "SELECT * FROM tokens WHERE hash=? AND kind='refresh'", (_hash(refresh_token),)
            ).fetchone()
        if not row or row["expires"] < time.time() or row["client_id"] != client.client_id:
            return None
        return RefreshToken(
            token=refresh_token, client_id=row["client_id"], scopes=row["scopes"].split(),
            expires_at=int(row["expires"]), resource=row["resource"], subject=row["subject"],
        )

    async def exchange_refresh_token(self, client, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        with db() as c:
            c.execute("DELETE FROM tokens WHERE hash=?", (_hash(refresh_token.token),))
        return self._issue(client.client_id, scopes or refresh_token.scopes, refresh_token.subject)

    async def load_access_token(self, token: str) -> AccessToken | None:
        with db() as c:
            row = c.execute("SELECT * FROM tokens WHERE hash=? AND kind='access'", (_hash(token),)).fetchone()
        if not row or row["expires"] < time.time():
            return None
        return AccessToken(
            token=token, client_id=row["client_id"], scopes=row["scopes"].split(),
            expires_at=int(row["expires"]), resource=row["resource"], subject=row["subject"],
        )

    async def revoke_token(self, token) -> None:
        with db() as c:
            c.execute("DELETE FROM tokens WHERE hash=?", (_hash(token.token),))


provider = Provider()

# ---------------------------------------------------------------- MCP tools

mcp = MCPServer(
    "mcp-home",
    title="mcp-home",
    instructions="Memo, upload and transcribe tools. See the plan page for what each tool keeps.",
    website_url=f"{PUBLIC_URL}/plan",
    auth_server_provider=provider,
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(PUBLIC_URL),
        resource_server_url=AnyHttpUrl(RESOURCE),
        service_documentation_url=AnyHttpUrl(f"{PUBLIC_URL}/plan"),
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]
        ),
        revocation_options=RevocationOptions(enabled=True),
        required_scopes=[SCOPE],
        validate_token_resource=True,
    ),
)


def _caller() -> tuple[str, str | None]:
    tok = get_access_token()
    client_id = tok.client_id if tok else "unknown"
    with db() as c:
        row = c.execute("SELECT info FROM clients WHERE client_id=?", (client_id,)).fetchone()
    name = json.loads(row["info"]).get("client_name") if row else None
    return client_id, name


class MemoWriteResult(BaseModel):
    id: str = Field(description="The new note's id.")
    created_at: float = Field(description="When it was saved, Unix seconds.")


class Note(BaseModel):
    id: str
    text: str
    created_at: float = Field(description="Unix seconds.")
    source: str | None = Field(description="Name of the client that saved it.")


class MemoSearchResult(BaseModel):
    notes: list[Note] = Field(description="Matching notes, newest first, at most 50.")


class UploadResult(BaseModel):
    url: str = Field(description="Public link to the file, served by this server. Anyone with it can open it.")
    id: str
    filename: str
    content_type: str
    size: int = Field(description="Bytes.")


class Segment(BaseModel):
    start: float = Field(description="Start of the segment, seconds from the beginning of the audio.")
    end: float = Field(description="End of the segment, seconds.")
    text: str


class TranscribeResult(BaseModel):
    segments: list[Segment]
    language: str | None = None
    duration: float | None = Field(default=None, description="Audio length, seconds.")


def _result(model: BaseModel, text: str | None = None) -> CallToolResult:
    # The SDK's default text block is indented JSON, which doubles the result size; keep it compact.
    data = model.model_dump(mode="json")
    body = text if text is not None else json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    return CallToolResult(content=[TextContent(type="text", text=body)], structured_content=data)


@mcp.tool(title="Save a note")
def memo_write(text: str = Field(description="The note to save.", min_length=1, max_length=MAX_MEMO)) -> Annotated[CallToolResult, MemoWriteResult]:
    """Save a note on this server. Returns its id."""
    client_id, name = _caller()
    note_id, now = secrets.token_hex(8), time.time()
    with db() as c:
        c.execute("INSERT INTO memos VALUES (?,?,?,?,?)", (note_id, text, client_id, name, now))
    return _result(MemoWriteResult(id=note_id, created_at=now))


@mcp.tool(title="Find notes")
def memo_search(
    query: str = Field(description="Words to look for; a note matches when it contains every word. Empty returns the newest notes.")
) -> Annotated[CallToolResult, MemoSearchResult]:
    """Find saved notes by text, newest first."""
    terms = query.split()
    where = " AND ".join("text LIKE ? ESCAPE '\\'" for _ in terms) or "1=1"
    args = ["%" + re.sub(r"([%_\\])", r"\\\1", t) + "%" for t in terms]
    with db() as c:
        rows = c.execute(f"SELECT * FROM memos WHERE {where} ORDER BY created_at DESC LIMIT 50", args).fetchall()
    return _result(MemoSearchResult(
        notes=[Note(id=r["id"], text=r["text"], created_at=r["created_at"], source=r["client_name"]) for r in rows]
    ))


@mcp.tool(title="Upload a file")
def upload(
    filename: str = Field(description="File name, e.g. clip.mp3. Used in the link and for the content type."),
    content_base64: str = Field(description="The file's bytes, base64-encoded. At most 25 MB decoded."),
    content_type: str | None = Field(default=None, description="MIME type. Guessed from the file name when left out."),
) -> Annotated[CallToolResult, UploadResult]:
    """Store a file on this server and return a public link that serves it."""
    try:
        data = base64.b64decode(content_base64, validate=True)
    except ValueError as e:
        raise ToolError(f"content_base64 for {filename} is not valid base64: {e}") from e
    if len(data) > MAX_UPLOAD:
        raise ToolError(f"{filename} is {len(data)} bytes; the limit is {MAX_UPLOAD}")
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name).strip(".") or "file"
    ctype = content_type or mimetypes.guess_type(safe)[0] or "application/octet-stream"
    file_id = secrets.token_urlsafe(12)
    (FILES_DIR / file_id).write_bytes(data)
    client_id, _ = _caller()
    with db() as c:
        c.execute("INSERT INTO uploads VALUES (?,?,?,?,?,?)", (file_id, safe, ctype, len(data), client_id, time.time()))
    return _result(UploadResult(url=f"{PUBLIC_URL}/files/{file_id}/{safe}", id=file_id, filename=safe, content_type=ctype, size=len(data)))


_whisper = None


def _transcribe_file(path: str, url: str) -> CallToolResult:
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel

        _whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    try:
        segments, info = _whisper.transcribe(path, vad_filter=True)
        out = [Segment(start=round(s.start, 2), end=round(s.end, 2), text=s.text.strip()) for s in segments]
    except Exception as e:  # noqa: BLE001 - PyAV raises many types for undecodable input
        raise ToolError(f"{url}: could not be decoded as audio ({type(e).__name__})") from e
    result = TranscribeResult(segments=out, language=info.language, duration=round(info.duration, 2))
    # Plain transcript as the text block: a second copy of the JSON would double the size.
    return _result(result, "\n".join(f"[{s.start:g}s] {s.text}" for s in out) or "(no speech found)")


@mcp.tool(title="Transcribe audio")
async def transcribe(
    url: str = Field(description="http(s) link to an audio or video file, such as a link from the upload tool. At most 100 MB."),
) -> Annotated[CallToolResult, TranscribeResult]:
    """Turn the audio at a URL into timestamped text segments (start and end in seconds)."""
    own = re.fullmatch(re.escape(PUBLIC_URL) + r"/files/([A-Za-z0-9_-]+)/[^/]*", url)
    if own and (FILES_DIR / own.group(1)).is_file():
        # Own links are read from disk: from fred, its public name resolves to a tailnet address.
        return await anyio.to_thread.run_sync(_transcribe_file, str(FILES_DIR / own.group(1)), url)
    data, ctype = await safe_get(url, MAX_AUDIO)
    kind = ctype.split(";")[0].strip().lower()
    if kind.startswith("text/") or kind in ("application/json", "application/xhtml+xml", "application/xml"):
        raise ToolError(f"{url}: not audio; it is a {kind} document")
    if not data:
        raise ToolError(f"{url}: the file is empty")
    with tempfile.NamedTemporaryFile(suffix=Path(urlparse(url).path).suffix or ".audio") as f:
        f.write(data)
        f.flush()
        return await anyio.to_thread.run_sync(_transcribe_file, f.name, url)


# ---------------------------------------------------------------- public HTTP routes

PLAN = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>mcp-home plan</title><style>body{{font:16px/1.5 system-ui,sans-serif;max-width:46rem;margin:2rem auto;padding:0 1rem;color:#222;background:#fff}}
code{{background:#f2f2f2;padding:0 .25rem;border-radius:3px}}@media(prefers-color-scheme:dark){{body{{color:#ddd;background:#161616}}code{{background:#2a2a2a}}}}</style></head><body>
<h1>mcp-home</h1>
<p>A personal remote MCP server. Endpoint: <code>{RESOURCE}</code> (Streamable HTTP, MCP 2026-07-28, older handshake revisions also accepted).</p>
<h2>Tools</h2>
<ul>
<li><b>memo_write</b> <code>{{text}}</code> → <code>{{id, created_at}}</code>: saves a note.</li>
<li><b>memo_search</b> <code>{{query}}</code> → <code>{{notes: [{{id, text, created_at, source}}]}}</code>: notes containing every word of the query, newest first, at most 50. An empty query returns the newest notes.</li>
<li><b>upload</b> <code>{{filename, content_base64, content_type?}}</code> → <code>{{url, id, filename, content_type, size}}</code>: stores a file (at most 25 MB) and returns a link under <code>{PUBLIC_URL}/files/</code>. Anyone with the link can open it.</li>
<li><b>transcribe</b> <code>{{url}}</code> → <code>{{segments: [{{start, end, text}}], language, duration}}</code>: speech to text with Whisper ({WHISPER_MODEL}) on this machine; times in seconds. The URL must be public http(s), at most 100 MB.</li>
</ul>
<p>Every tool declares an output schema and returns matching structured content.</p>
<h2>Sign-in</h2>
<p>OAuth 2.1 with PKCE (S256). Metadata: <code>/.well-known/oauth-protected-resource/mcp</code> and <code>/.well-known/oauth-authorization-server</code>. Clients identify with a Client ID Metadata Document (an https <code>client_id</code>) or register at <code>/register</code>. Every authorization stops at a consent page that only the owner can reach, on the owner's private network; nobody gets a token until the owner approves that request. Access tokens are bound to <code>{RESOURCE}</code>, last one hour, and refresh tokens last 30 days. Tokens never go in URLs.</p>
<h2>Data kept</h2>
<ul>
<li>Notes: text, the saving client's id and name, the time. Kept until the owner deletes them. Every approved client can read every note.</li>
<li>Uploads: the file, its name, type, size, the uploading client and the time. Public by link until the owner deletes them.</li>
<li>Transcribe: the audio is held only while it is transcribed, then deleted. The transcript is returned, not stored.</li>
<li>Sign-in: registered client metadata, and SHA-256 hashes of codes and tokens until they expire.</li>
</ul>
<p>No analytics, no third parties. Transcription runs on this machine.</p>
</body></html>"""


async def plan_page(_: Request) -> Response:
    return HTMLResponse(PLAN)


async def protected_resource_metadata(_: Request) -> Response:
    return JSONResponse(
        {
            "resource": RESOURCE,
            "authorization_servers": [PUBLIC_URL],
            "scopes_supported": [SCOPE],
            "bearer_methods_supported": ["header"],
            "resource_name": "mcp-home",
            "resource_documentation": f"{PUBLIC_URL}/plan",
        },
        headers={"Access-Control-Allow-Origin": "*"},
    )


async def authorization_server_metadata(_: Request) -> Response:
    return JSONResponse(
        {
            "issuer": PUBLIC_URL,
            "authorization_endpoint": f"{PUBLIC_URL}/authorize",
            "token_endpoint": f"{PUBLIC_URL}/token",
            "registration_endpoint": f"{PUBLIC_URL}/register",
            "revocation_endpoint": f"{PUBLIC_URL}/revoke",
            "scopes_supported": [SCOPE],
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
            "revocation_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
            "code_challenge_methods_supported": ["S256"],
            "client_id_metadata_document_supported": True,
            "authorization_response_iss_parameter_supported": True,
            "service_documentation": f"{PUBLIC_URL}/plan",
        },
        headers={"Access-Control-Allow-Origin": "*"},
    )


async def serve_file(request: Request) -> Response:
    file_id = request.path_params["id"]
    with db() as c:
        row = c.execute("SELECT * FROM uploads WHERE id=?", (file_id,)).fetchone()
    if not row or not (FILES_DIR / file_id).is_file():
        return Response("not found", status_code=404)
    # Uploads share an origin with the OAuth endpoints, so they never run as active content here.
    return FileResponse(
        FILES_DIR / file_id,
        media_type=row["content_type"],
        headers={
            "Content-Security-Policy": "sandbox; default-src 'none'; media-src 'self'; img-src 'self'",
            "X-Content-Type-Options": "nosniff",
            "Access-Control-Allow-Origin": "*",
            "Content-Disposition": f'inline; filename="{row["filename"]}"',
        },
    )


async def root(_: Request) -> Response:
    return RedirectResponse(f"{PUBLIC_URL}/plan")


def public_app() -> Starlette:
    app = mcp.streamable_http_app(
        stateless_http=True,
        json_response=True,
        max_request_body_size=40 * 1024 * 1024,
        # Behind Funnel the Host is the public name, and every MCP call needs a bearer token anyway.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    # Ours first: the SDK's metadata routes lack resource_documentation and the CIMD flag.
    app.router.routes[0:0] = [
        Route("/.well-known/oauth-protected-resource/mcp", protected_resource_metadata, methods=["GET"]),
        Route("/.well-known/oauth-protected-resource", protected_resource_metadata, methods=["GET"]),
        Route("/.well-known/oauth-authorization-server", authorization_server_metadata, methods=["GET"]),
        Route("/plan", plan_page, methods=["GET"]),
        Route("/files/{id}/{name}", serve_file, methods=["GET", "HEAD"]),
        Route("/", root, methods=["GET"]),
    ]
    return app


# ---------------------------------------------------------------- owner consent (tailnet only)

CONSENT_STYLE = (
    "body{font:16px/1.5 system-ui,sans-serif;max-width:36rem;margin:2rem auto;padding:0 1rem;color:#222;background:#fff}"
    "button{font-size:1rem;padding:.6rem 1.2rem;margin-right:.5rem}"
    "@media(prefers-color-scheme:dark){body{color:#ddd;background:#161616}}"
)


def _owner(request: Request) -> str | None:
    login = request.headers.get("tailscale-user-login", "").lower()
    return login if login in OWNER_LOGINS else None


def _page(body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        f'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>mcp-home sign-in</title><style>{CONSENT_STYLE}</style>{body}",
        status_code=status,
        headers={"X-Frame-Options": "DENY", "Content-Security-Policy": "frame-ancestors 'none'"},
    )


async def consent_get(request: Request) -> Response:
    owner = _owner(request)
    if not owner:
        return _page("<h1>Not allowed</h1><p>Only the owner, on the owner's tailnet, can approve sign-ins.</p>", 403)
    req_id = request.query_params.get("req", "")
    csrf = secrets.token_urlsafe(24)
    with db() as c:
        row = c.execute("SELECT * FROM pending WHERE id=? AND expires>?", (req_id, time.time())).fetchone()
        if row:
            c.execute("UPDATE pending SET csrf=? WHERE id=?", (csrf, req_id))
    if not row:
        return _page("<h1>Expired</h1><p>This sign-in request is unknown or expired. Start again from the client.</p>", 404)
    client = await provider.get_client(row["client_id"])
    params = AuthorizationParams.model_validate_json(row["params"])
    e = html.escape
    return _page(
        f"<h1>Let this client in?</h1>"
        f"<p><b>{e(client.client_name or 'Unnamed client') if client else 'Unknown client'}</b></p>"
        f"<p>Client id: <code>{e(row['client_id'])}</code><br>Returns to: <code>{e(str(params.redirect_uri))}</code><br>"
        f"Access: all tools on <code>{e(RESOURCE)}</code>, including every saved note.</p>"
        f'<form method="post" action="/consent"><input type="hidden" name="req" value="{e(req_id)}">'
        f'<input type="hidden" name="csrf" value="{csrf}">'
        f'<button name="decision" value="approve">Approve</button><button name="decision" value="deny">Deny</button></form>'
        f"<p><small>Signed in to the tailnet as {e(owner)}.</small></p>"
    )


async def consent_post(request: Request) -> Response:
    owner = _owner(request)
    origin = request.headers.get("origin")
    if not owner or (origin and origin.rstrip("/") != CONSENT_URL):
        return _page("<h1>Not allowed</h1>", 403)
    form = await request.form()
    req_id, csrf, decision = str(form.get("req", "")), str(form.get("csrf", "")), form.get("decision")
    with db() as c:
        row = c.execute("SELECT * FROM pending WHERE id=? AND expires>?", (req_id, time.time())).fetchone()
        if not row or not row["csrf"] or not secrets.compare_digest(row["csrf"], csrf):
            return _page("<h1>Expired</h1><p>Start again from the client.</p>", 400)
        c.execute("DELETE FROM pending WHERE id=?", (req_id,))
    params = AuthorizationParams.model_validate_json(row["params"])
    redirect = str(params.redirect_uri)
    if decision != "approve":
        log.info("owner denied client %s", row["client_id"])
        return RedirectResponse(
            construct_redirect_uri(redirect, error="access_denied", state=params.state, iss=PUBLIC_URL), 303
        )
    code = secrets.token_urlsafe(32)
    auth_code = AuthorizationCode(
        code=code, scopes=params.scopes or [SCOPE], expires_at=time.time() + CODE_TTL, client_id=row["client_id"],
        code_challenge=params.code_challenge, redirect_uri=params.redirect_uri,
        redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly, resource=RESOURCE, subject=owner,
    )
    with db() as c:
        c.execute("INSERT INTO codes VALUES (?,?,?)", (_hash(code), auth_code.model_dump_json(), auth_code.expires_at))
    log.info("owner approved client %s", row["client_id"])
    return RedirectResponse(construct_redirect_uri(redirect, code=code, state=params.state, iss=PUBLIC_URL), 303)


consent_app = Starlette(
    routes=[Route("/consent", consent_get, methods=["GET"]), Route("/consent", consent_post, methods=["POST"])]
)


async def main() -> None:
    servers = [
        uvicorn.Server(uvicorn.Config(public_app(), host="127.0.0.1", port=PUBLIC_PORT, proxy_headers=True,
                                      forwarded_allow_ips="127.0.0.1", log_level="info")),
        uvicorn.Server(uvicorn.Config(consent_app, host="127.0.0.1", port=CONSENT_PORT, log_level="info")),
    ]
    async with anyio.create_task_group() as tg:
        for s in servers:
            tg.start_soon(s.serve)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    anyio.run(main)
