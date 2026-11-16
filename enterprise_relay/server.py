"""HTTP entry point for the cross-platform Enterprise Relay Server MVP."""

from __future__ import annotations

import argparse
import json
import logging
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import ssl
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from . import __version__
from .store import RelayError, RelayStore


LOG = logging.getLogger("cfquant.enterprise_relay")


def _header(headers: Dict[str, str], name: str) -> str:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return ""


def _bearer(headers: Dict[str, str]) -> str:
    value = _header(headers, "Authorization")
    prefix = "Bearer "
    if value.startswith(prefix):
        return value[len(prefix):].strip()
    return ""


class RelayApplication:
    """Route HTTP requests to the persistent RelayStore."""

    def __init__(self, store: RelayStore):
        self.store = store

    @staticmethod
    def _ok(data: Any) -> Dict[str, Any]:
        return {"ok": True, "data": data}

    @staticmethod
    def _payload(payload: Any) -> Dict[str, Any]:
        if payload is None:
            return {}
        if not isinstance(payload, dict):
            raise RelayError("invalid_json", "请求体必须是 JSON 对象")
        return payload

    def _admin(self, headers: Dict[str, str]) -> Dict[str, Any]:
        return self.store.authenticate_admin(_bearer(headers))

    def _node(self, headers: Dict[str, str]) -> Dict[str, Any]:
        return self.store.authenticate_node(_bearer(headers))

    def dispatch(self, method: str, path: str, payload: Any = None,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        headers = headers or {}
        path = urlsplit(path).path.rstrip("/") or "/"
        body = self._payload(payload)

        if method == "GET" and path == "/api/v1/health":
            return self._ok({"service": "cfquant-enterprise-relay", "version": __version__, **self.store.status()})

        if method == "POST" and path == "/api/v1/auth/bootstrap":
            return self._ok(self.store.bootstrap(
                body.get("activation_code", ""), body.get("username", ""), body.get("password", "")
            ))

        if method == "POST" and path == "/api/v1/auth/login":
            return self._ok(self.store.login(body.get("username", ""), body.get("password", "")))

        if method == "POST" and path == "/api/v1/auth/logout":
            self._admin(headers)
            self.store.logout(_bearer(headers))
            return self._ok({"logged_out": True})

        if method == "GET" and path == "/api/v1/admin/status":
            self._admin(headers)
            return self._ok(self.store.status())

        if method == "GET" and path == "/api/v1/admin/entitlement":
            self._admin(headers)
            return self._ok(self.store.entitlement())

        if method == "GET" and path == "/api/v1/admin/nodes":
            self._admin(headers)
            return self._ok({"nodes": self.store.list_nodes()})

        if method == "POST" and path == "/api/v1/admin/pairing":
            admin = self._admin(headers)
            return self._ok(self.store.create_pairing(admin, body.get("ttl_seconds", 600)))

        if method == "POST" and path == "/api/v1/admin/nodes/revoke":
            admin = self._admin(headers)
            self.store.revoke_node(admin, body.get("node_id", ""))
            return self._ok({"revoked": True, "node_id": body.get("node_id")})

        if method == "POST" and path == "/api/v1/nodes/claim":
            return self._ok(self.store.claim_node(body))

        if method == "POST" and path == "/api/v1/nodes/heartbeat":
            node = self._node(headers)
            return self._ok(self.store.heartbeat(node, body))

        if method == "POST" and path == "/api/v1/messages/send":
            node = self._node(headers)
            return self._ok(self.store.send_message(node, body))

        if method == "POST" and path == "/api/v1/messages/poll":
            node = self._node(headers)
            return self._ok(self.store.poll_messages(node, body))

        raise RelayError("not_found", "接口不存在", 404)


class RelayHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, app: RelayApplication):
        self.app = app
        super().__init__(address, RelayRequestHandler)


class RelayRequestHandler(BaseHTTPRequestHandler):
    """Small JSON HTTP adapter; TLS is expected at a reverse proxy in MVP."""

    protocol_version = "HTTP/1.1"
    server_version = "CFQuantRelay"
    sys_version = ""
    MAX_BODY_BYTES = 2 * 1024 * 1024

    def _write(self, status: int, payload: Dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _handle(self, method: str, payload: Any = None) -> None:
        try:
            result = self.server.app.dispatch(method, self.path, payload, dict(self.headers.items()))
            self._write(HTTPStatus.OK, result)
        except RelayError as error:
            self._write(error.status, {"ok": False, "error": {"code": error.code, "message": error.message}})
        except Exception:
            LOG.exception("unhandled relay request method=%s path=%s", method, self.path)
            self._write(HTTPStatus.INTERNAL_SERVER_ERROR, {
                "ok": False, "error": {"code": "internal_error", "message": "服务端内部错误"}
            })

    def _read_json(self) -> Any:
        value = self.headers.get("Content-Length", "0")
        try:
            length = int(value)
        except ValueError:
            raise RelayError("invalid_content_length", "Content-Length 无效")
        if length < 0 or length > self.MAX_BODY_BYTES:
            raise RelayError("payload_too_large", "请求体超出大小限制", 413)
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RelayError("invalid_json", "请求体必须是 UTF-8 JSON")
        return value

    def do_GET(self) -> None:  # noqa: N802
        self._handle("GET")

    def do_POST(self) -> None:  # noqa: N802
        try:
            payload = self._read_json()
        except RelayError as error:
            self._write(error.status, {"ok": False, "error": {"code": error.code, "message": error.message}})
            return
        self._handle("POST", payload)

    def log_message(self, format: str, *args: Any) -> None:
        LOG.info("%s - %s", self.address_string(), format % args)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CFQuant Enterprise Relay Server")
    parser.add_argument("--host", default=os.environ.get("CFQUANT_RELAY_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("CFQUANT_RELAY_PORT", "8890")))
    parser.add_argument("--data-dir", default=os.environ.get(
        "CFQUANT_RELAY_DATA_DIR", str(Path.home() / ".cfquant-relay")
    ))
    parser.add_argument("--activation-code", default=os.environ.get("CFQUANT_RELAY_ACTIVATION_CODE", ""),
                        help="首次激活使用的一次性代码；也可以使用 CFQUANT_RELAY_ACTIVATION_CODE")
    parser.add_argument("--relay-mode", choices=("official", "self_hosted"),
                        default=os.environ.get("CFQUANT_RELAY_MODE", "self_hosted"))
    parser.add_argument("--plan", default=os.environ.get("CFQUANT_RELAY_PLAN", "enterprise"))
    parser.add_argument("--market-forwarding", action="store_true",
                        default=os.environ.get("CFQUANT_RELAY_MARKET_FORWARDING", "0") == "1",
                        help="启用企业版行情转发能力")
    parser.add_argument("--tls-certfile", default=os.environ.get("CFQUANT_RELAY_TLS_CERTFILE", ""),
                        help="直接提供 HTTPS 服务时使用的证书文件")
    parser.add_argument("--tls-keyfile", default=os.environ.get("CFQUANT_RELAY_TLS_KEYFILE", ""),
                        help="直接提供 HTTPS 服务时使用的私钥文件")
    parser.add_argument("--log-level", default=os.environ.get("CFQUANT_RELAY_LOG_LEVEL", "INFO"))
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    data_dir = Path(args.data_dir).expanduser().resolve()
    entitlement = {
        "plan": args.plan,
        "relay_mode": args.relay_mode,
        "features": {"market_forwarding": bool(args.market_forwarding), "trade_routing": True},
        "limits": {"max_nodes": 50, "max_market_bps": None},
    }
    store = RelayStore(data_dir / "relay.sqlite3", activation_code=args.activation_code,
                       entitlement=entitlement)
    app = RelayApplication(store)
    server = RelayHTTPServer((args.host, args.port), app)
    if bool(args.tls_certfile) != bool(args.tls_keyfile):
        server.server_close()
        raise SystemExit("--tls-certfile 和 --tls-keyfile 必须同时提供")
    scheme = "http"
    if args.tls_certfile:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(args.tls_certfile, args.tls_keyfile)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        scheme = "https"
    LOG.info("CFQuant Relay Server %s listening on %s://%s:%s data_dir=%s mode=%s",
             __version__, scheme, args.host, args.port, data_dir, args.relay_mode)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOG.info("stopping relay server")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
