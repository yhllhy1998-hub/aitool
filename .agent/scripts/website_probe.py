#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import ssl
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlsplit


DEFAULT_TIMEOUT = 10.0


@dataclass(frozen=True)
class ProxyConfig:
    host: str
    port: int

    @property
    def address(self) -> tuple[str, int]:
        return self.host, self.port

    @property
    def display(self) -> str:
        return f"{self.host}:{self.port}"


@dataclass(frozen=True)
class Route:
    name: str
    proxy: ProxyConfig | None = None


@dataclass(frozen=True)
class HttpCheck:
    name: str
    host: str
    port: int
    path: str
    method: str = "HEAD"
    headers: tuple[tuple[str, str], ...] = ()
    body_text: str = ""

    @property
    def url(self) -> str:
        suffix = "" if self.port == 443 else f":{self.port}"
        return f"https://{self.host}{suffix}{self.path}"


@dataclass(frozen=True)
class WsCheck:
    name: str
    host: str
    port: int
    path: str

    @property
    def url(self) -> str:
        suffix = "" if self.port == 443 else f":{self.port}"
        return f"wss://{self.host}{suffix}{self.path}"


def slugify(value: str) -> str:
    slug = "".join(character.lower() if character.isalnum() else "_" for character in value)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "root"


def parse_proxy(value: str) -> ProxyConfig:
    text = value.strip()
    if text.startswith("http://"):
        text = text[7:]
    elif text.startswith("https://"):
        text = text[8:]
    if "/" in text:
        text = text.split("/", 1)[0]
    if ":" not in text:
        raise ValueError(f"proxy must be HOST:PORT, got {value!r}")
    host, port_text = text.rsplit(":", 1)
    if not host:
        raise ValueError(f"proxy host is missing in {value!r}")
    try:
        port = int(port_text)
    except ValueError as exc:
        raise ValueError(f"proxy port must be an integer, got {port_text!r}") from exc
    return ProxyConfig(host=host, port=port)


def parse_proxy_server_setting(value: str) -> list[ProxyConfig]:
    text = value.strip()
    if not text:
        return []

    entries: list[str] = []
    if "=" not in text:
        entries.append(text)
    else:
        parts = [part.strip() for part in text.split(";") if part.strip()]
        ordered = []
        prioritized = ["https", "http", "socks", "socks5"]
        for key in prioritized:
            for part in parts:
                if part.lower().startswith(f"{key}="):
                    ordered.append(part.split("=", 1)[1].strip())
        for part in parts:
            if "=" in part:
                _, proxy_text = part.split("=", 1)
                proxy_text = proxy_text.strip()
                if proxy_text and proxy_text not in ordered:
                    ordered.append(proxy_text)
        entries.extend(ordered)

    proxies: list[ProxyConfig] = []
    seen: set[str] = set()
    for entry in entries:
        proxy = parse_proxy(entry)
        if proxy.display not in seen:
            seen.add(proxy.display)
            proxies.append(proxy)
    return proxies


def detect_windows_system_proxies() -> list[ProxyConfig]:
    if os.name != "nt":
        return []
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
        proxy_enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
        if not proxy_enabled:
            return []
        proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
        if not proxy_server:
            return []
    except OSError:
        return []
    return parse_proxy_server_setting(str(proxy_server))


def parse_header(value: str) -> tuple[str, str]:
    if ":" not in value:
        raise ValueError(f"header must use 'Name: Value' format, got {value!r}")
    name, header_value = value.split(":", 1)
    name = name.strip()
    header_value = header_value.strip()
    if not name:
        raise ValueError(f"header name is missing in {value!r}")
    return name, header_value


def build_routes(proxy_values: Iterable[str], include_direct: bool, auto_proxy: bool = False) -> list[Route]:
    proxies = [parse_proxy(value) for value in proxy_values]
    if auto_proxy:
        for detected in detect_windows_system_proxies():
            if all(existing.display != detected.display for existing in proxies):
                proxies.append(detected)

    routes: list[Route] = []
    if include_direct or not proxies:
        routes.append(Route(name="direct"))
    for proxy in proxies:
        routes.append(Route(name=f"proxy_{slugify(proxy.display)}", proxy=proxy))
    return routes


def parse_https_check(
    url: str,
    *,
    index: int,
    method: str,
    headers: tuple[tuple[str, str], ...],
    body_text: str,
) -> HttpCheck:
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise ValueError(f"HTTP target must use https://, got {url!r}")
    if not parsed.hostname:
        raise ValueError(f"HTTP target host is missing in {url!r}")
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    name = f"{method.lower()}_{slugify(parsed.hostname)}_{slugify(path)}_{index}"
    return HttpCheck(
        name=name,
        host=parsed.hostname,
        port=parsed.port or 443,
        path=path,
        method=method.upper(),
        headers=headers,
        body_text=body_text,
    )


def parse_wss_check(url: str, *, index: int) -> WsCheck:
    parsed = urlsplit(url)
    if parsed.scheme != "wss":
        raise ValueError(f"WebSocket target must use wss://, got {url!r}")
    if not parsed.hostname:
        raise ValueError(f"WebSocket target host is missing in {url!r}")
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    name = f"wss_{slugify(parsed.hostname)}_{slugify(path)}_{index}"
    return WsCheck(name=name, host=parsed.hostname, port=parsed.port or 443, path=path)


def build_codex_suite(host: str, port: int) -> list[HttpCheck | WsCheck]:
    return [
        HttpCheck(name="root_head", host=host, port=port, path="/", method="HEAD"),
        HttpCheck(
            name="ps_plugins_list",
            host=host,
            port=port,
            path="/backend-api/ps/plugins/list?scope=GLOBAL&limit=1",
            method="GET",
        ),
        HttpCheck(
            name="ps_plugins_installed",
            host=host,
            port=port,
            path="/backend-api/ps/plugins/installed?scope=USER",
            method="GET",
        ),
        HttpCheck(
            name="ps_plugins_installed_workspace",
            host=host,
            port=port,
            path="/backend-api/ps/plugins/installed?scope=WORKSPACE",
            method="GET",
        ),
        HttpCheck(
            name="ps_mcp",
            host=host,
            port=port,
            path="/backend-api/ps/mcp",
            method="POST",
            headers=(("Accept", "application/json"), ("Content-Type", "application/json")),
            body_text="{}",
        ),
        HttpCheck(
            name="codex_responses_head",
            host=host,
            port=port,
            path="/backend-api/codex/responses",
            method="HEAD",
        ),
        WsCheck(name="codex_responses_wss", host=host, port=port, path="/backend-api/codex/responses"),
    ]


def collect_checks(
    *,
    preset: str | None,
    host: str,
    port: int,
    target_urls: Iterable[str],
    wss_urls: Iterable[str],
    method: str,
    header_values: Iterable[str],
    body_text: str,
) -> list[HttpCheck | WsCheck]:
    checks: list[HttpCheck | WsCheck] = []
    if preset == "codex":
        checks.extend(build_codex_suite(host, port))

    headers = tuple(parse_header(value) for value in header_values)
    for index, url in enumerate(target_urls, start=1):
        checks.append(
            parse_https_check(
                url,
                index=index,
                method=method.upper(),
                headers=headers,
                body_text=body_text,
            )
        )
    for index, url in enumerate(wss_urls, start=1):
        checks.append(parse_wss_check(url, index=index))

    if not checks:
        raise ValueError("no checks requested; use --preset, --target, or --wss")
    return checks


def read_until(sock: socket.socket, marker: bytes = b"\r\n\r\n", limit: int = 65536) -> bytes:
    payload = b""
    while marker not in payload and len(payload) < limit:
        chunk = sock.recv(4096)
        if not chunk:
            break
        payload += chunk
    return payload


def first_line(data: bytes) -> str:
    text = data.decode("iso-8859-1", errors="replace")
    return text.splitlines()[0] if text else ""


def is_connect_success(status_line: str) -> bool:
    return status_line.startswith("HTTP/1.1 200") or status_line.startswith("HTTP/1.0 200")


def unique_authorities(checks: Iterable[HttpCheck | WsCheck]) -> list[tuple[str, int]]:
    seen: set[tuple[str, int]] = set()
    authorities: list[tuple[str, int]] = []
    for check in checks:
        key = (check.host, check.port)
        if key not in seen:
            seen.add(key)
            authorities.append(key)
    return authorities


def parse_status_code(status_line: str | None) -> int | None:
    if not status_line:
        return None
    parts = status_line.split()
    if len(parts) < 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def classify_result(result: dict[str, object]) -> str:
    if result.get("connect_error") or result.get("tls_error") or result.get("request_error"):
        return "error"
    if result["kind"] == "https_connect":
        return "reachable" if is_connect_success(str(result.get("proxy_connect_response") or "")) else "blocked"
    if result.get("response_line"):
        return "reachable"
    return "unknown"


def summarize_result(result: dict[str, object]) -> str:
    fragments: list[str] = []
    if result.get("tcp_connect") == "ok":
        fragments.append("TCP ok")
    if result.get("proxy_connect_response"):
        fragments.append(f"CONNECT {result['proxy_connect_response']}")
    if result.get("tls_handshake") == "ok":
        fragments.append("TLS ok")
    if result.get("response_line"):
        fragments.append(str(result["response_line"]))
    if result.get("connect_error"):
        fragments.append(f"connect error: {result['connect_error']}")
    if result.get("tls_error"):
        fragments.append(f"TLS error: {result['tls_error']}")
    if result.get("request_error"):
        fragments.append(f"request error: {result['request_error']}")
    return "; ".join(fragments) or "no result"


def open_tls_session(host: str, port: int, route: Route, timeout: float) -> tuple[dict[str, object], ssl.SSLSocket | None]:
    details: dict[str, object] = {
        "proxy": route.proxy.display if route.proxy else None,
        "tcp_connect": None,
        "proxy_connect_response": None,
        "tls_handshake": None,
        "tls_error": None,
    }
    raw_socket: socket.socket | None = None
    tls_socket: ssl.SSLSocket | None = None
    try:
        destination = route.proxy.address if route.proxy else (host, port)
        raw_socket = socket.create_connection(destination, timeout=timeout)
        raw_socket.settimeout(timeout)
        details["tcp_connect"] = "ok"
        if route.proxy:
            request = (
                f"CONNECT {host}:{port} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                f"Proxy-Connection: Keep-Alive\r\n"
                f"User-Agent: website-probe/1.0\r\n\r\n"
            ).encode("ascii")
            raw_socket.sendall(request)
            response = read_until(raw_socket)
            status_line = first_line(response)
            details["proxy_connect_response"] = status_line
            if not is_connect_success(status_line):
                raise ConnectionError(f"proxy CONNECT failed: {status_line or 'no response'}")
        context = ssl.create_default_context()
        tls_socket = context.wrap_socket(raw_socket, server_hostname=host)
        details["tls_handshake"] = "ok"
        return details, tls_socket
    except Exception as exc:
        details["tls_error"] = f"{type(exc).__name__}: {exc}"
        if tls_socket is not None:
            try:
                tls_socket.close()
            except OSError:
                pass
        elif raw_socket is not None:
            try:
                raw_socket.close()
            except OSError:
                pass
        return details, None


def run_connect_check(route: Route, host: str, port: int, timeout: float) -> dict[str, object]:
    result: dict[str, object] = {
        "route": route.name,
        "kind": "https_connect",
        "name": f"https_connect_{host}_{port}",
        "host": host,
        "port": port,
        "proxy": route.proxy.display if route.proxy else None,
        "tcp_connect": None,
        "proxy_connect_response": None,
        "connect_error": None,
    }
    if route.proxy is None:
        result["connect_error"] = "no proxy configured for this route"
        result["outcome"] = classify_result(result)
        result["summary"] = summarize_result(result)
        return result

    raw_socket: socket.socket | None = None
    try:
        raw_socket = socket.create_connection(route.proxy.address, timeout=timeout)
        raw_socket.settimeout(timeout)
        result["tcp_connect"] = "ok"
        request = (
            f"CONNECT {host}:{port} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Proxy-Connection: Keep-Alive\r\n"
            f"User-Agent: website-probe/1.0\r\n\r\n"
        ).encode("ascii")
        raw_socket.sendall(request)
        response = read_until(raw_socket)
        result["proxy_connect_response"] = first_line(response)
    except Exception as exc:
        result["connect_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if raw_socket is not None:
            try:
                raw_socket.close()
            except OSError:
                pass

    result["status_code"] = parse_status_code(result.get("proxy_connect_response"))
    result["outcome"] = classify_result(result)
    result["summary"] = summarize_result(result)
    return result


def run_http_check(route: Route, check: HttpCheck, timeout: float) -> dict[str, object]:
    result: dict[str, object] = {
        "route": route.name,
        "kind": "http",
        "name": check.name,
        "method": check.method,
        "url": check.url,
        "path": check.path,
    }
    details, tls_socket = open_tls_session(check.host, check.port, route, timeout)
    result.update(details)
    if tls_socket is None:
        result["status_code"] = None
        result["outcome"] = classify_result(result)
        result["summary"] = summarize_result(result)
        return result

    try:
        body = check.body_text.encode("utf-8")
        headers = {
            "Host": check.host,
            "Connection": "close",
            "User-Agent": "website-probe/1.0",
        }
        for name, value in check.headers:
            headers[name] = value
        if body and "Content-Length" not in headers:
            headers["Content-Length"] = str(len(body))
        request = (
            f"{check.method} {check.path} HTTP/1.1\r\n"
            + "".join(f"{name}: {value}\r\n" for name, value in headers.items())
            + "\r\n"
        ).encode("utf-8")
        tls_socket.sendall(request + body)
        response = read_until(tls_socket)
        result["response_line"] = first_line(response)
    except Exception as exc:
        result["request_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            tls_socket.close()
        except OSError:
            pass

    result["status_code"] = parse_status_code(result.get("response_line"))
    result["outcome"] = classify_result(result)
    result["summary"] = summarize_result(result)
    return result


def run_ws_check(route: Route, check: WsCheck, timeout: float) -> dict[str, object]:
    result: dict[str, object] = {
        "route": route.name,
        "kind": "wss",
        "name": check.name,
        "url": check.url,
        "path": check.path,
    }
    details, tls_socket = open_tls_session(check.host, check.port, route, timeout)
    result.update(details)
    if tls_socket is None:
        result["status_code"] = None
        result["outcome"] = classify_result(result)
        result["summary"] = summarize_result(result)
        return result

    try:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {check.path} HTTP/1.1\r\n"
            f"Host: {check.host}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"User-Agent: website-probe/1.0\r\n\r\n"
        ).encode("ascii")
        tls_socket.sendall(request)
        response = read_until(tls_socket)
        result["response_line"] = first_line(response)
    except Exception as exc:
        result["request_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            tls_socket.close()
        except OSError:
            pass

    result["status_code"] = parse_status_code(result.get("response_line"))
    result["outcome"] = classify_result(result)
    result["summary"] = summarize_result(result)
    return result


def probe_checks(checks: list[HttpCheck | WsCheck], routes: list[Route], timeout: float) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    authorities = unique_authorities(checks)

    for route in routes:
        if route.proxy is not None:
            for host, port in authorities:
                results.append(run_connect_check(route, host, port, timeout))
        for check in checks:
            if isinstance(check, HttpCheck):
                results.append(run_http_check(route, check, timeout))
            else:
                results.append(run_ws_check(route, check, timeout))
    return results


def probe_from_values(
    *,
    preset: str | None,
    host: str,
    port: int,
    target_urls: Iterable[str],
    wss_urls: Iterable[str],
    method: str,
    header_values: Iterable[str],
    body_text: str,
    proxy_values: Iterable[str],
    include_direct: bool,
    auto_proxy: bool,
    timeout: float,
) -> list[dict[str, object]]:
    checks = collect_checks(
        preset=preset,
        host=host,
        port=port,
        target_urls=target_urls,
        wss_urls=wss_urls,
        method=method,
        header_values=header_values,
        body_text=body_text,
    )
    routes = build_routes(proxy_values, include_direct=include_direct, auto_proxy=auto_proxy)
    return probe_checks(checks, routes, timeout)


def format_label(result: dict[str, object]) -> str:
    if result["kind"] == "http":
        return f"{result['name']} [{result['method']} {result['path']}]"
    if result["kind"] == "wss":
        return f"{result['name']} [WSS {result['path']}]"
    return f"{result['name']} [CONNECT {result['host']}:{result['port']}]"


def format_results(results: list[dict[str, object]]) -> str:
    lines: list[str] = []
    current_route: str | None = None
    for result in results:
        route_name = str(result["route"])
        if route_name != current_route:
            if lines:
                lines.append("")
            lines.append(f"Route: {route_name}")
            current_route = route_name
        lines.append(f"- {format_label(result)} -> {result['summary']}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe HTTPS CONNECT, HTTPS, and WSS reachability for websites and Codex backend endpoints."
    )
    parser.add_argument("--preset", choices=["codex"], help="Run the built-in Codex backend suite.")
    parser.add_argument("--host", default="chatgpt.com", help="Host used by the built-in preset.")
    parser.add_argument("--port", type=int, default=443, help="Port used by the built-in preset.")
    parser.add_argument("--target", action="append", default=[], help="HTTPS URL to probe. Repeat for multiple targets.")
    parser.add_argument("--wss", action="append", default=[], help="WSS URL to probe. Repeat for multiple targets.")
    parser.add_argument("--method", default="HEAD", help="HTTP method used for --target URLs. Defaults to HEAD.")
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        help="Header applied to every --target request, for example 'Authorization: Bearer token'.",
    )
    parser.add_argument("--body", default="", help="Request body applied to every --target request.")
    parser.add_argument(
        "--proxy",
        action="append",
        default=[],
        help="Proxy route in HOST:PORT format, for example 127.0.0.1:7897. Repeat for multiple proxies.",
    )
    parser.add_argument("--auto-proxy", action="store_true", help="Include proxies detected from Windows system settings.")
    parser.add_argument("--include-direct", action="store_true", help="Probe direct access in addition to any proxy routes.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="Socket timeout in seconds.")
    parser.add_argument("--json", action="store_true", help="Print raw JSON instead of a text summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        results = probe_from_values(
            preset=args.preset,
            host=args.host,
            port=args.port,
            target_urls=args.target,
            wss_urls=args.wss,
            method=args.method,
            header_values=args.header,
            body_text=args.body,
            proxy_values=args.proxy,
            include_direct=args.include_direct,
            auto_proxy=args.auto_proxy,
            timeout=args.timeout,
        )
    except ValueError as exc:
        parser.error(str(exc))

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(format_results(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
