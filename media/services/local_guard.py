"""Protección de la API local contra páginas web ajenas.

La API escucha en 127.0.0.1 y no tiene login. Sin esta barrera, cualquier sitio abierto
en el navegador podría escribirle (CSRF: un POST «simple» a http://127.0.0.1:8000) o
leerla tras un DNS rebinding (un dominio ajeno que resuelve a 127.0.0.1).

* ``Host`` debe ser un nombre local (127.0.0.1, localhost, ::1 o los de ``ALLOWED_HOSTS``).
* Si llega ``Origin`` (los navegadores lo mandan en todo POST/PUT/DELETE entre orígenes),
  debe ser un origen local de los puertos de la app.
* Un ``Sec-Fetch-Site: cross-site`` solo se admite en lecturas (GET/HEAD).

Las llamadas de servidor a servidor (Next → FastAPI, curl) no llevan ``Origin``.
``web/lib/local-guard.ts`` aplica las mismas reglas del lado de Next.js: deben coincidir.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from urllib.parse import urlsplit

LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
SAFE_METHODS = frozenset({"GET", "HEAD"})


def allowed_hostnames(extra: str = "") -> frozenset[str]:
    """Nombres locales más los de ``ALLOWED_HOSTS`` (lista separada por comas)."""
    more = {h.strip().lower() for h in extra.split(",") if h.strip()}
    return LOOPBACK | more


def hostname_of(host_header: str) -> str | None:
    """Nombre sin puerto de un encabezado Host («127.0.0.1:8000», «[::1]:3000»)."""
    try:
        return urlsplit("//" + (host_header or "").strip()).hostname
    except ValueError:
        return None


def check(method: str, headers: Mapping[str, str], hosts: frozenset[str], ports: frozenset[int]) -> str | None:
    """Motivo del rechazo, o None si la petición puede seguir. ``headers`` en minúsculas."""
    name = hostname_of(headers.get("host", ""))
    if name is None or name not in hosts:
        return "Host no permitido"
    origin = headers.get("origin")
    if origin is not None:
        try:
            parts = urlsplit(origin)
            port = parts.port
        except ValueError:
            return "Origin no permitido"
        if parts.scheme not in ("http", "https") or parts.hostname not in hosts or port not in ports:
            return "Origin no permitido"
    if headers.get("sec-fetch-site") == "cross-site" and method.upper() not in SAFE_METHODS:
        return "Petición entre sitios no permitida"
    return None


def ports_from_env() -> frozenset[int]:
    out: set[int] = set()
    for key, default in (("MEDIA_PORT", 8000), ("WEB_PORT", 3000)):
        try:
            out.add(int(os.getenv(key) or default))
        except ValueError:
            out.add(default)
    return frozenset(out)


class LocalGuard:
    """Middleware ASGI puro (no envuelve la respuesta: los videos con Range siguen en streaming)."""

    def __init__(self, app, hosts: frozenset[str] | None = None, ports: frozenset[int] | None = None):
        self.app = app
        self.hosts = hosts or allowed_hostnames(os.getenv("ALLOWED_HOSTS", ""))
        self.ports = ports or ports_from_env()

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        reason = check(scope.get("method", "GET"), headers, self.hosts, self.ports)
        if reason is None:
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 1008})
        body = ('{"detail":"%s"}' % reason).encode()
        await send({"type": "http.response.start", "status": 403, "headers": [
            (b"content-type", b"application/json; charset=utf-8"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
