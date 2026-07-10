#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import website_probe


PAGE_TITLE = "Website Probe Workbench"

HTML_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Website Probe Workbench</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0f172a;
      --panel: #111827;
      --muted: #94a3b8;
      --border: #334155;
      --text: #e5e7eb;
      --ok: #16a34a;
      --warn: #d97706;
      --bad: #dc2626;
      --accent: #2563eb;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    .layout {
      display: grid;
      grid-template-columns: 380px 1fr;
      min-height: 100vh;
    }
    .sidebar, .content {
      padding: 20px;
    }
    .sidebar {
      border-right: 1px solid var(--border);
      background: rgba(15, 23, 42, 0.9);
    }
    .content {
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    h1, h2, h3 {
      margin: 0 0 12px;
    }
    .section {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 14px;
      margin-bottom: 14px;
    }
    label {
      display: block;
      font-size: 13px;
      margin: 10px 0 6px;
      color: var(--muted);
    }
    input, textarea, select, button {
      width: 100%;
      font: inherit;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: #0b1220;
      color: var(--text);
      padding: 10px 12px;
    }
    textarea {
      min-height: 80px;
      resize: vertical;
    }
    .row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }
    .inline {
      display: flex;
      gap: 10px;
      align-items: center;
      margin-top: 10px;
      flex-wrap: wrap;
    }
    .inline > label {
      margin: 0;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--text);
    }
    .inline input[type="checkbox"] {
      width: auto;
      margin: 0;
    }
    button {
      cursor: pointer;
      background: var(--accent);
      border: none;
      font-weight: 600;
    }
    button.secondary {
      background: #1f2937;
      border: 1px solid var(--border);
    }
    .summary {
      display: grid;
      grid-template-columns: repeat(4, minmax(110px, 1fr));
      gap: 12px;
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 14px;
    }
    .card strong {
      display: block;
      font-size: 24px;
      margin-top: 8px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 14px;
      overflow: hidden;
    }
    th, td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--border);
      vertical-align: top;
      text-align: left;
      font-size: 13px;
    }
    th {
      color: var(--muted);
      background: #0b1220;
      position: sticky;
      top: 0;
    }
    .badge {
      display: inline-block;
      padding: 4px 8px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
    }
    .badge.reachable { background: rgba(22, 163, 74, 0.18); color: #86efac; }
    .badge.error { background: rgba(220, 38, 38, 0.18); color: #fca5a5; }
    .badge.blocked { background: rgba(217, 119, 6, 0.18); color: #fdba74; }
    .badge.unknown { background: rgba(100, 116, 139, 0.18); color: #cbd5e1; }
    .muted { color: var(--muted); }
    .toolbar {
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
    }
    .toolbar .status {
      margin-left: auto;
      color: var(--muted);
      font-size: 13px;
    }
    details {
      white-space: pre-wrap;
    }
    @media (max-width: 1100px) {
      .layout { grid-template-columns: 1fr; }
      .sidebar { border-right: none; border-bottom: 1px solid var(--border); }
    }
  </style>
</head>
<body>
  <div class="layout">
    <aside class="sidebar">
      <h1>实时测试工作台</h1>
      <div class="section">
        <label for="preset">预设</label>
        <select id="preset">
          <option value="codex">Codex 后台链路</option>
          <option value="">自定义</option>
        </select>
        <div class="row">
          <div>
            <label for="host">Host</label>
            <input id="host" value="chatgpt.com" />
          </div>
          <div>
            <label for="port">Port</label>
            <input id="port" type="number" value="443" />
          </div>
        </div>
        <div class="inline">
          <label><input id="includeDirect" type="checkbox" checked />直连</label>
          <label><input id="autoProxy" type="checkbox" checked />自动读取系统代理</label>
        </div>
        <label for="proxies">手动代理（每行一个，例：127.0.0.1:7897）</label>
        <textarea id="proxies"></textarea>
      </div>

      <div class="section">
        <label for="targets">HTTPS 目标（每行一个）</label>
        <textarea id="targets" placeholder="https://example.com/health"></textarea>
        <label for="wssTargets">WSS 目标（每行一个）</label>
        <textarea id="wssTargets" placeholder="wss://example.com/socket"></textarea>
        <div class="row">
          <div>
            <label for="method">HTTP Method</label>
            <select id="method">
              <option>HEAD</option>
              <option>GET</option>
              <option>POST</option>
              <option>PUT</option>
            </select>
          </div>
          <div>
            <label for="timeout">超时（秒）</label>
            <input id="timeout" type="number" step="0.5" min="1" value="10" />
          </div>
        </div>
        <label for="headers">请求头（每行一个，例：Authorization: Bearer xxx）</label>
        <textarea id="headers"></textarea>
        <label for="body">请求体</label>
        <textarea id="body">{}</textarea>
      </div>

      <div class="section">
        <div class="toolbar">
          <button id="runButton">立即测试</button>
          <button id="fillButton" class="secondary" type="button">填入当前代理</button>
        </div>
        <div class="inline">
          <label><input id="autoRefresh" type="checkbox" />自动刷新</label>
          <input id="refreshSeconds" type="number" min="2" value="5" style="width: 90px;" />
          <span class="muted">秒</span>
        </div>
      </div>
    </aside>

    <main class="content">
      <div class="toolbar">
        <h2>探测结果</h2>
        <div class="status" id="statusText">等待首次测试</div>
      </div>

      <div class="summary" id="summaryCards">
        <div class="card"><div class="muted">总检查项</div><strong id="summaryTotal">0</strong></div>
        <div class="card"><div class="muted">可达</div><strong id="summaryReachable">0</strong></div>
        <div class="card"><div class="muted">错误</div><strong id="summaryError">0</strong></div>
        <div class="card"><div class="muted">阻断/未知</div><strong id="summaryOther">0</strong></div>
      </div>

      <table>
        <thead>
          <tr>
            <th>Route</th>
            <th>检查项</th>
            <th>状态</th>
            <th>URL / Path</th>
            <th>摘要</th>
            <th>详情</th>
          </tr>
        </thead>
        <tbody id="resultsBody"></tbody>
      </table>
    </main>
  </div>

  <script>
    const state = {
      timer: null,
      config: null,
    };

    function splitLines(text) {
      return text.split(/\\r?\\n/).map(item => item.trim()).filter(Boolean);
    }

    function badgeClass(outcome) {
      return ['reachable', 'error', 'blocked'].includes(outcome) ? outcome : 'unknown';
    }

    function setStatus(text) {
      document.getElementById('statusText').textContent = text;
    }

    function fillProxyTextarea() {
      const proxies = (state.config?.detected_proxies || []).join('\\n');
      document.getElementById('proxies').value = proxies;
    }

    function collectPayload() {
      return {
        preset: document.getElementById('preset').value || null,
        host: document.getElementById('host').value.trim() || 'chatgpt.com',
        port: Number(document.getElementById('port').value || 443),
        proxies: splitLines(document.getElementById('proxies').value),
        include_direct: document.getElementById('includeDirect').checked,
        auto_proxy: document.getElementById('autoProxy').checked,
        targets: splitLines(document.getElementById('targets').value),
        wss: splitLines(document.getElementById('wssTargets').value),
        method: document.getElementById('method').value,
        headers: splitLines(document.getElementById('headers').value),
        body: document.getElementById('body').value,
        timeout: Number(document.getElementById('timeout').value || 10),
      };
    }

    function renderSummary(results) {
      const counts = { total: results.length, reachable: 0, error: 0, other: 0 };
      for (const result of results) {
        if (result.outcome === 'reachable') counts.reachable += 1;
        else if (result.outcome === 'error') counts.error += 1;
        else counts.other += 1;
      }
      document.getElementById('summaryTotal').textContent = counts.total;
      document.getElementById('summaryReachable').textContent = counts.reachable;
      document.getElementById('summaryError').textContent = counts.error;
      document.getElementById('summaryOther').textContent = counts.other;
    }

    function renderResults(results) {
      const tbody = document.getElementById('resultsBody');
      tbody.innerHTML = '';
      for (const result of results) {
        const row = document.createElement('tr');
        row.innerHTML = `
          <td>${result.route || ''}</td>
          <td>${result.name || ''}<div class="muted">${result.kind || ''}</div></td>
          <td><span class="badge ${badgeClass(result.outcome)}">${result.outcome || 'unknown'}</span></td>
          <td>${result.url || result.path || `${result.host || ''}:${result.port || ''}`}</td>
          <td>${result.summary || ''}</td>
          <td><details><summary>展开</summary>${JSON.stringify(result, null, 2)}</details></td>
        `;
        tbody.appendChild(row);
      }
    }

    async function runProbe() {
      const payload = collectPayload();
      setStatus('测试中...');
      try {
        const response = await fetch('/api/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        renderSummary(data.results);
        renderResults(data.results);
        setStatus(`最近运行：${data.generated_at}`);
      } catch (error) {
        setStatus(`测试失败：${error.message}`);
      }
    }

    function restartAutoRefresh() {
      if (state.timer) {
        clearInterval(state.timer);
        state.timer = null;
      }
      if (document.getElementById('autoRefresh').checked) {
        const seconds = Math.max(2, Number(document.getElementById('refreshSeconds').value || 5));
        state.timer = setInterval(runProbe, seconds * 1000);
      }
    }

    async function bootstrap() {
      const response = await fetch('/api/config');
      state.config = await response.json();
      if (state.config.detected_proxies?.length) {
        fillProxyTextarea();
      }
      document.getElementById('runButton').addEventListener('click', runProbe);
      document.getElementById('fillButton').addEventListener('click', fillProxyTextarea);
      document.getElementById('autoRefresh').addEventListener('change', restartAutoRefresh);
      document.getElementById('refreshSeconds').addEventListener('change', restartAutoRefresh);
      await runProbe();
    }

    bootstrap();
  </script>
</body>
</html>
"""


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_lines(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    return []


def build_run_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "preset": payload.get("preset") or None,
        "host": str(payload.get("host") or "chatgpt.com").strip() or "chatgpt.com",
        "port": int(payload.get("port") or 443),
        "proxy_values": parse_lines(payload.get("proxies")),
        "include_direct": bool(payload.get("include_direct", True)),
        "auto_proxy": bool(payload.get("auto_proxy", True)),
        "target_urls": parse_lines(payload.get("targets")),
        "wss_urls": parse_lines(payload.get("wss")),
        "method": str(payload.get("method") or "HEAD").upper(),
        "header_values": parse_lines(payload.get("headers")),
        "body_text": str(payload.get("body") or ""),
        "timeout": float(payload.get("timeout") or website_probe.DEFAULT_TIMEOUT),
    }


class WorkbenchHandler(BaseHTTPRequestHandler):
    server_version = "WebsiteProbeWorkbench/1.0"

    def log_message(self, format: str, *args: object) -> None:
        return

    def send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_html(HTML_PAGE)
            return
        if parsed.path == "/api/config":
            proxies = [proxy.display for proxy in website_probe.detect_windows_system_proxies()]
            self.send_json(
                HTTPStatus.OK,
                {
                    "title": PAGE_TITLE,
                    "generated_at": now_text(),
                    "detected_proxies": proxies,
                    "default_preset": "codex",
                    "default_host": "chatgpt.com",
                    "default_port": 443,
                },
            )
            return
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/run":
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            payload = json.loads(raw.decode("utf-8"))
            probe_payload = build_run_payload(payload)
            results = website_probe.probe_from_values(**probe_payload)
            self.send_json(
                HTTPStatus.OK,
                {
                    "generated_at": now_text(),
                    "results": results,
                },
            )
        except Exception as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": f"{type(exc).__name__}: {exc}"})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local interactive workbench for website connectivity probes.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host. Defaults to 127.0.0.1.")
    parser.add_argument("--port", type=int, default=8765, help="Bind port. Defaults to 8765.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), WorkbenchHandler)
    print(f"Website Probe Workbench running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
