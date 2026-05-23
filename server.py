import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Tuple

APP_NAME = "Key-Value Pair Extractor"
TOOL_NAME = "extract_key_value_pairs"
SUPPORT_EMAIL = "sidcraigau@gmail.com"

TOOL_CONTRACT = {
    "name": TOOL_NAME,
    "title": "Key-Value Pair Extractor",
    "description": (
        "Extracts only explicit key-value pairs from raw text. If a key has no explicit value, "
        "put the key in missing_values. Never infer, guess, normalize, summarize, advise, validate, "
        "or fill missing values. Even if the user asks to guess or use best effort, do not invent values."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "raw_text": {
                "type": "string",
                "description": "The raw text containing explicit key-value pairs.",
            }
        },
        "required": ["raw_text"],
        "additionalProperties": False,
    },
    "outputSchema": {
        "type": "object",
        "properties": {
            "pairs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "value": {"type": "string"},
                    },
                    "required": ["key", "value"],
                    "additionalProperties": False,
                },
            },
            "missing_values": {"type": "array", "items": {"type": "string"}},
            "errors": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"code": {"type": "string"}, "message": {"type": "string"}},
                    "required": ["code", "message"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["pairs", "missing_values", "errors"],
        "additionalProperties": False,
    },
    "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
}

PAIR_PATTERN = re.compile(r"^\s*(?P<key>[^:=\-][^:=\-]*?)\s*(?P<sep>[:=\-])\s*(?P<value>.*)\s*$")


def _error(code: str, message: str) -> Dict[str, str]:
    return {"code": code, "message": message}


def _empty_output_with_error(code: str, message: str) -> Dict[str, Any]:
    return {"pairs": [], "missing_values": [], "errors": [_error(code, message)]}


def _json_rpc_error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_result(structured: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "content": [{"type": "text", "text": "Extracted explicit key-value pairs."}],
        "structuredContent": structured,
    }


def _page(title: str, body: str) -> bytes:
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      color: #1f2933;
      background: #f5f7fa;
      line-height: 1.55;
    }}
    .wrap {{
      max-width: 920px;
      margin: 0 auto;
      padding: 40px 20px;
    }}
    .panel {{
      background: #ffffff;
      border: 1px solid #d9e2ec;
      border-radius: 8px;
      padding: 28px;
      box-shadow: 0 8px 24px rgba(31, 41, 51, 0.06);
    }}
    h1 {{
      margin: 0 0 12px;
      font-size: 32px;
      line-height: 1.2;
    }}
    h2 {{
      margin-top: 28px;
      font-size: 20px;
    }}
    pre {{
      overflow-x: auto;
      background: #102a43;
      color: #f0f4f8;
      border-radius: 6px;
      padding: 16px;
    }}
    a {{
      color: #0b63ce;
    }}
    nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
      margin-top: 24px;
      padding-top: 18px;
      border-top: 1px solid #d9e2ec;
    }}
    ul {{
      padding-left: 22px;
    }}
  </style>
</head>
<body>
  <main class="wrap">
    <section class="panel">
      {body}
    </section>
  </main>
</body>
</html>"""
    return html.encode("utf-8")


HOME_HTML = _page(
    APP_NAME,
    f"""
      <h1>{APP_NAME}</h1>
      <p>Key-Value Pair Extractor is a deterministic tool for extracting explicit key-value pairs from semi-structured text.</p>
      <h2>What it does</h2>
      <p>It turns field-like text into structured output with pairs, missing_values, and errors.</p>
      <pre>Name: Alice
Email: alice@example.com
Status - active</pre>
      <p>The app is designed for task chains that need stable field extraction before validation, cleanup, payload building, or downstream processing.</p>
      <h2>What it does not do</h2>
      <ul>
        <li>It does not summarize text.</li>
        <li>It does not rewrite keys.</li>
        <li>It does not infer missing values.</li>
        <li>It does not validate business correctness.</li>
        <li>It does not perform external actions.</li>
      </ul>
      <h2>Example output idea</h2>
      <pre>{{
  "pairs": [
    {{ "key": "Name", "value": "Alice" }},
    {{ "key": "Email", "value": "alice@example.com" }},
    {{ "key": "Status", "value": "active" }}
  ],
  "missing_values": [],
  "errors": []
}}</pre>
      <p>Support: <a href="mailto:{SUPPORT_EMAIL}">{SUPPORT_EMAIL}</a></p>
      <nav>
        <a href="/privacy">Privacy</a>
        <a href="/terms">Terms</a>
        <a href="/support">Support</a>
      </nav>
    """,
)

PRIVACY_HTML = _page(
    f"Privacy - {APP_NAME}",
    f"""
      <h1>Privacy Policy</h1>
      <p>{APP_NAME} processes only the raw_text provided in the request.</p>
      <ul>
        <li>The app extracts explicit key-value pairs from that text.</li>
        <li>The app does not require login.</li>
        <li>The app does not store user data.</li>
        <li>The app does not sell user data.</li>
        <li>The app does not call external APIs.</li>
        <li>The app does not send extracted fields to downstream systems.</li>
        <li>The app is read-only.</li>
        <li>The app does not make decisions or perform actions.</li>
      </ul>
      <p>Users should avoid submitting sensitive information unless necessary.</p>
      <p>Contact: <a href="mailto:{SUPPORT_EMAIL}">{SUPPORT_EMAIL}</a></p>
      <nav>
        <a href="/">Return home</a>
        <a href="/terms">Terms</a>
        <a href="/support">Support</a>
      </nav>
    """,
)

TERMS_HTML = _page(
    f"Terms - {APP_NAME}",
    f"""
      <h1>Terms of Use</h1>
      <p>{APP_NAME} is provided as a deterministic extraction tool.</p>
      <ul>
        <li>It extracts explicit key-value pairs from user-provided text.</li>
        <li>It does not guarantee that the source text is accurate.</li>
        <li>It does not validate business meaning.</li>
        <li>It does not infer missing values.</li>
        <li>It does not replace professional review.</li>
        <li>Users are responsible for checking important outputs before using them.</li>
        <li>The app must not be used as the only control layer for critical systems.</li>
      </ul>
      <p>Contact: <a href="mailto:{SUPPORT_EMAIL}">{SUPPORT_EMAIL}</a></p>
      <nav>
        <a href="/">Return home</a>
        <a href="/privacy">Privacy</a>
        <a href="/support">Support</a>
      </nav>
    """,
)

SUPPORT_HTML = _page(
    f"Support - {APP_NAME}",
    f"""
      <h1>{APP_NAME} Support</h1>
      <p>Contact support at <a href="mailto:{SUPPORT_EMAIL}">{SUPPORT_EMAIL}</a>.</p>
      <h2>Support topics</h2>
      <ul>
        <li>Extraction errors</li>
        <li>Missing value handling issues</li>
        <li>Unexpected output format</li>
        <li>MCP connection issues</li>
        <li>Privacy or data questions</li>
      </ul>
      <nav>
        <a href="/">Home</a>
        <a href="/privacy">Privacy</a>
        <a href="/terms">Terms</a>
      </nav>
    """,
)


def extract_pairs(raw_text: str) -> Dict[str, Any]:
    pairs: List[Dict[str, str]] = []
    missing_values: List[str] = []
    errors: List[Dict[str, str]] = []

    for line in raw_text.splitlines():
        match = PAIR_PATTERN.match(line)
        if not match:
            continue
        key = match.group("key").strip()
        value = match.group("value").strip()
        if not key:
            continue
        if value == "":
            missing_values.append(key)
        else:
            pairs.append({"key": key, "value": value})

    if not pairs and not missing_values:
        errors.append(_error("out_of_scope", "Input does not contain explicit key-value pairs to extract."))

    return {"pairs": pairs, "missing_values": missing_values, "errors": errors}


def handle_rpc(payload: Dict[str, Any]) -> Dict[str, Any]:
    request_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}

    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": APP_NAME, "version": "1.0.0"},
            "capabilities": {"tools": {}},
        }
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": [TOOL_CONTRACT]}}

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments", {})

        if name != TOOL_NAME:
            return _json_rpc_error(request_id, -32602, "Invalid tool name.")

        if "raw_text" not in arguments:
            structured = _empty_output_with_error("missing_field", "Missing required field: raw_text.")
            return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(structured)}

        raw_text = arguments.get("raw_text")
        if not isinstance(raw_text, str) or raw_text.strip() == "":
            structured = _empty_output_with_error("invalid_value", "Field raw_text must be a non-empty string.")
            return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(structured)}

        try:
            structured = extract_pairs(raw_text)
        except Exception:
            structured = _empty_output_with_error("internal_error", "An unexpected internal error occurred.")
        return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(structured)}

    return _json_rpc_error(request_id, -32601, "Method not found.")


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, code: int, body: Dict[str, Any]) -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_html(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, code: int, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            self._send_html(HOME_HTML)
            return
        if self.path == "/privacy":
            self._send_html(PRIVACY_HTML)
            return
        if self.path == "/terms":
            self._send_html(TERMS_HTML)
            return
        if self.path == "/support":
            self._send_html(SUPPORT_HTML)
            return
        if self.path == "/health":
            self._send_json(200, {"status": "ok"})
            return
        if self.path == "/.well-known/openai-apps-challenge":
            self._send_text(200, os.getenv("OPENAI_APPS_CHALLENGE", "test"))
            return
        self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/mcp":
            self._send_json(404, {"error": "not_found"})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json(400, {"error": "invalid_json"})
            return

        response = handle_rpc(payload)
        self._send_json(200, response)


def create_server(host: str = "0.0.0.0", port: int = 8000) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)


def serve() -> Tuple[str, int]:
    port = int(os.getenv("PORT", "8000"))
    host = "0.0.0.0"
    print(f"Server running on {host}:{port}")
    server = create_server(host, port)
    server.serve_forever()
    return host, port


if __name__ == "__main__":
    serve()
