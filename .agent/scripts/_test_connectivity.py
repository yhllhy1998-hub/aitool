import base64
import json
import os
import socket
import ssl
from urllib.parse import urlsplit

HOST = 'chatgpt.com'
PORT = 443
PROXY = ('127.0.0.1', 7897)
TIMEOUT = 10


def recv_until(sock, marker=b'\r\n\r\n', limit=65536):
    data = b''
    while marker not in data and len(data) < limit:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    return data


def open_tls(host, port=443, proxy=None):
    details = {
        'proxy': f'{proxy[0]}:{proxy[1]}' if proxy else None,
        'tcp_connect': None,
        'proxy_connect_response': None,
        'tls_handshake': None,
        'tls_error': None,
    }
    raw = None
    tls_sock = None
    try:
        target = proxy if proxy else (host, port)
        raw = socket.create_connection(target, timeout=TIMEOUT)
        raw.settimeout(TIMEOUT)
        details['tcp_connect'] = 'ok'
        if proxy:
            req = (
                f'CONNECT {host}:{port} HTTP/1.1\r\n'
                f'Host: {host}:{port}\r\n'
                f'Proxy-Connection: Keep-Alive\r\n'
                f'User-Agent: CodexConnectivityTest/1.0\r\n\r\n'
            ).encode('ascii')
            raw.sendall(req)
            proxy_resp = recv_until(raw)
            text = proxy_resp.decode('iso-8859-1', errors='replace')
            first_line = text.splitlines()[0] if text else ''
            details['proxy_connect_response'] = first_line
            if ' 200 ' not in f' {first_line} ':
                return details, None
        context = ssl.create_default_context()
        context.check_hostname = True
        tls_sock = context.wrap_socket(raw, server_hostname=host)
        details['tls_handshake'] = 'ok'
        return details, tls_sock
    except Exception as exc:
        details['tls_error'] = f'{type(exc).__name__}: {exc}'
        try:
            if tls_sock:
                tls_sock.close()
        finally:
            if raw:
                raw.close()
        return details, None


def do_http(name, method, path, headers=None, body=b'', proxy=None):
    result = {'name': name, 'kind': 'http', 'method': method, 'path': path}
    conn, sock = None, None
    details, sock = open_tls(HOST, PORT, proxy=proxy)
    result.update(details)
    if not sock:
        return result
    try:
        hdrs = {
            'Host': HOST,
            'Connection': 'close',
            'User-Agent': 'CodexConnectivityTest/1.0',
        }
        if headers:
            hdrs.update(headers)
        if body:
            hdrs['Content-Length'] = str(len(body))
        req = f'{method} {path} HTTP/1.1\r\n' + ''.join(f'{k}: {v}\r\n' for k, v in hdrs.items()) + '\r\n'
        sock.sendall(req.encode('utf-8') + body)
        resp = recv_until(sock)
        text = resp.decode('iso-8859-1', errors='replace')
        first_line = text.splitlines()[0] if text else ''
        result['response_line'] = first_line
        result['reachable'] = bool(first_line)
        return result
    except Exception as exc:
        result['request_error'] = f'{type(exc).__name__}: {exc}'
        return result
    finally:
        try:
            sock.close()
        except Exception:
            pass


def do_ws(name, path, proxy=None):
    result = {'name': name, 'kind': 'wss', 'path': path}
    details, sock = open_tls(HOST, PORT, proxy=proxy)
    result.update(details)
    if not sock:
        return result
    try:
        key = base64.b64encode(os.urandom(16)).decode('ascii')
        req = (
            f'GET {path} HTTP/1.1\r\n'
            f'Host: {HOST}\r\n'
            f'Upgrade: websocket\r\n'
            f'Connection: Upgrade\r\n'
            f'Sec-WebSocket-Key: {key}\r\n'
            f'Sec-WebSocket-Version: 13\r\n'
            f'User-Agent: CodexConnectivityTest/1.0\r\n\r\n'
        ).encode('ascii')
        sock.sendall(req)
        resp = recv_until(sock)
        text = resp.decode('iso-8859-1', errors='replace')
        first_line = text.splitlines()[0] if text else ''
        result['response_line'] = first_line
        result['reachable'] = bool(first_line)
        return result
    except Exception as exc:
        result['request_error'] = f'{type(exc).__name__}: {exc}'
        return result
    finally:
        try:
            sock.close()
        except Exception:
            pass


tests = []
for proxy_label, proxy in [('direct', None), ('proxy_127.0.0.1_7897', PROXY)]:
    tests.append((proxy_label, do_http('root_head', 'HEAD', '/', proxy=proxy)))
    tests.append((proxy_label, do_http('ps_plugins_list', 'GET', '/backend-api/ps/plugins/list?scope=GLOBAL&limit=1', proxy=proxy)))
    tests.append((proxy_label, do_http('ps_plugins_installed', 'GET', '/backend-api/ps/plugins/installed?scope=USER', proxy=proxy)))
    tests.append((proxy_label, do_http('ps_mcp', 'POST', '/backend-api/ps/mcp', headers={'Accept':'application/json','Content-Type':'application/json'}, body=b'{}', proxy=proxy)))
    tests.append((proxy_label, do_http('codex_responses_head', 'HEAD', '/backend-api/codex/responses', proxy=proxy)))
    tests.append((proxy_label, do_ws('codex_responses_wss', '/backend-api/codex/responses', proxy=proxy)))

out = []
for label, data in tests:
    item = {'route': label}
    item.update(data)
    out.append(item)
print(json.dumps(out, ensure_ascii=False, indent=2))
