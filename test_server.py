import json
import threading
import urllib.error
import urllib.request

from server import TOOL_NAME, create_server


server = None
port = None


def setup_module(_module):
    global server, port
    server = create_server("127.0.0.1", 0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()


def teardown_module(_module):
    server.shutdown()
    server.server_close()


def request(method, url, body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        return resp.status, resp.read().decode("utf-8"), dict(resp.headers)


def rpc(method, params=None, req_id=1):
    payload = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        payload["params"] = params
    status, raw, _headers = request("POST", f"http://127.0.0.1:{port}/mcp", payload)
    return status, json.loads(raw)


def call_tool(raw_text=None, arguments=None, req_id=1):
    if arguments is None:
        arguments = {}
        if raw_text is not None:
            arguments["raw_text"] = raw_text
    return rpc("tools/call", {"name": TOOL_NAME, "arguments": arguments}, req_id)


def structured(data):
    return data["result"]["structuredContent"]


def assert_output_shape(content):
    assert set(content) == {"pairs", "missing_values", "errors"}
    assert isinstance(content["pairs"], list)
    assert isinstance(content["missing_values"], list)
    assert isinstance(content["errors"], list)


def test_get_root_returns_successfully():
    status, body, headers = request("GET", f"http://127.0.0.1:{port}/")
    assert status == 200
    assert "text/html" in headers["Content-Type"]
    assert "Key-Value Pair Extractor" in body
    assert "explicit key-value pairs" in body
    assert 'href="/privacy"' in body
    assert 'href="/terms"' in body
    assert 'href="/support"' in body
    assert "pairs" in body
    assert "missing_values" in body
    assert "errors" in body


def test_get_privacy_returns_successfully():
    status, body, headers = request("GET", f"http://127.0.0.1:{port}/privacy")
    assert status == 200
    assert "text/html" in headers["Content-Type"]
    assert "Privacy Policy" in body
    assert "does not store user data" in body
    assert "does not call external APIs" in body
    assert "Return home" in body


def test_get_terms_returns_successfully():
    status, body, headers = request("GET", f"http://127.0.0.1:{port}/terms")
    assert status == 200
    assert "text/html" in headers["Content-Type"]
    assert "Terms of Use" in body
    assert "does not infer missing values" in body
    assert "Return home" in body


def test_get_support_returns_successfully_and_contains_contact():
    status, body, headers = request("GET", f"http://127.0.0.1:{port}/support")
    assert status == 200
    assert "text/html" in headers["Content-Type"]
    assert "Key-Value Pair Extractor Support" in body
    assert "sidcraigau@gmail.com" in body
    assert 'href="/"' in body
    assert 'href="/privacy"' in body
    assert 'href="/terms"' in body


def test_get_health_returns_successfully():
    status, body, _headers = request("GET", f"http://127.0.0.1:{port}/health")
    assert status == 200
    assert json.loads(body) == {"status": "ok"}


def test_get_openai_apps_challenge_returns_successfully(monkeypatch):
    monkeypatch.setenv("OPENAI_APPS_CHALLENGE", "review-shell-token")
    status, body, headers = request("GET", f"http://127.0.0.1:{port}/.well-known/openai-apps-challenge")
    assert status == 200
    assert "text/plain" in headers["Content-Type"]
    assert body == "review-shell-token"


def test_post_mcp_and_initialize_work():
    status, data = rpc("initialize")
    assert status == 200
    result = data["result"]
    assert "protocolVersion" in result
    assert result["serverInfo"]["name"] == "Key-Value Pair Extractor"
    assert "capabilities" in result


def test_tools_list_contract_is_complete():
    status, data = rpc("tools/list")
    assert status == 200
    tools = data["result"]["tools"]
    assert len(tools) == 1
    tool = tools[0]
    assert tool["name"] == TOOL_NAME
    assert tool["title"] == "Key-Value Pair Extractor"
    assert "Extracts only explicit key-value pairs" in tool["description"]
    assert "Even if the user asks to guess" in tool["description"]
    assert "inputSchema" in tool
    assert "outputSchema" in tool
    assert "annotations" in tool
    assert tool["annotations"] == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "openWorldHint": False,
    }


def test_tools_list_schemas_include_required_fields_and_additional_properties():
    _, data = rpc("tools/list")
    tool = data["result"]["tools"][0]
    input_schema = tool["inputSchema"]
    output_schema = tool["outputSchema"]
    pair_schema = output_schema["properties"]["pairs"]["items"]
    error_schema = output_schema["properties"]["errors"]["items"]

    assert input_schema["required"] == ["raw_text"]
    assert input_schema["additionalProperties"] is False
    assert output_schema["required"] == ["pairs", "missing_values", "errors"]
    assert output_schema["additionalProperties"] is False
    assert pair_schema["required"] == ["key", "value"]
    assert pair_schema["additionalProperties"] is False
    assert error_schema["required"] == ["code", "message"]
    assert error_schema["additionalProperties"] is False


def test_tools_call_extracts_colon_separated_pairs():
    _, data = call_tool("Name: Alice\nEmail: alice@example.com\nStatus: active")
    assert set(data["result"]) == {"content", "structuredContent"}
    assert data["result"]["content"] == [{"type": "text", "text": "Extracted explicit key-value pairs."}]
    assert structured(data) == {
        "pairs": [
            {"key": "Name", "value": "Alice"},
            {"key": "Email", "value": "alice@example.com"},
            {"key": "Status", "value": "active"},
        ],
        "missing_values": [],
        "errors": [],
    }


def test_tools_call_extracts_equals_separated_pairs():
    _, data = call_tool("Email = alice@example.com")
    assert structured(data)["pairs"] == [{"key": "Email", "value": "alice@example.com"}]


def test_tools_call_extracts_dash_separated_pairs():
    _, data = call_tool("Status - active")
    assert structured(data)["pairs"] == [{"key": "Status", "value": "active"}]


def test_tools_call_handles_missing_values():
    _, data = call_tool("Name: Emma Stone\nEmail:\nStatus: active\nDepartment:\nLocation: Berlin")
    assert structured(data) == {
        "pairs": [
            {"key": "Name", "value": "Emma Stone"},
            {"key": "Status", "value": "active"},
            {"key": "Location", "value": "Berlin"},
        ],
        "missing_values": ["Email", "Department"],
        "errors": [],
    }


def test_tools_call_returns_missing_field_when_raw_text_is_missing():
    _, data = call_tool(arguments={})
    content = structured(data)
    assert_output_shape(content)
    assert content["errors"] == [{"code": "missing_field", "message": "Missing required field: raw_text."}]


def test_tools_call_returns_invalid_value_when_raw_text_is_empty():
    for value in ("", "   ", None, 123):
        _, data = call_tool(arguments={"raw_text": value})
        content = structured(data)
        assert_output_shape(content)
        assert content["errors"][0]["code"] == "invalid_value"


def test_tools_call_returns_out_of_scope_when_no_pairs_exist():
    _, data = call_tool("Please summarize this customer note and tell me what to do next.")
    assert structured(data) == {
        "pairs": [],
        "missing_values": [],
        "errors": [
            {
                "code": "out_of_scope",
                "message": "Input does not contain explicit key-value pairs to extract.",
            }
        ],
    }


def test_tools_call_does_not_summarize():
    _, data = call_tool("Please summarize this customer note and tell me what to do next.")
    assert structured(data)["pairs"] == []
    assert structured(data)["errors"][0]["code"] == "out_of_scope"


def test_tools_call_does_not_return_flattened_top_level_json_object():
    _, data = call_tool("Name: Alice\nEmail: alice@example.com")
    content = structured(data)
    assert_output_shape(content)
    assert "Name" not in content
    assert "Email" not in content
    assert content["pairs"] == [
        {"key": "Name", "value": "Alice"},
        {"key": "Email", "value": "alice@example.com"},
    ]


def test_tools_call_does_not_rewrite_keys():
    _, data = call_tool(" Customer Email = alice@example.com ")
    assert structured(data)["pairs"] == [{"key": "Customer Email", "value": "alice@example.com"}]


def test_tools_call_preserves_exact_long_keys():
    key = "Very Long Customer Provided Field Name With Original Capitalization"
    _, data = call_tool(f"{key}: preserved")
    assert structured(data)["pairs"] == [{"key": key, "value": "preserved"}]


def test_tools_call_does_not_infer_missing_values():
    _, data = call_tool("Name: Alice\nEmail:")
    content = structured(data)
    assert content["pairs"] == [{"key": "Name", "value": "Alice"}]
    assert content["missing_values"] == ["Email"]
    assert "Email" not in [pair["key"] for pair in content["pairs"]]


def test_tools_call_best_guess_prompt_does_not_infer_or_suggest_values():
    raw_text = "Name: Olivia Martin\nEmail:\nCompany: BrightLabs\n\nUse your best guess for the missing email if possible."
    _, data = call_tool(raw_text)
    content = structured(data)
    assert content == {
        "pairs": [
            {"key": "Name", "value": "Olivia Martin"},
            {"key": "Company", "value": "BrightLabs"},
        ],
        "missing_values": ["Email"],
        "errors": [],
    }
    serialized = json.dumps(data)
    assert "Unknown" not in serialized
    assert "olivia" not in serialized.lower().replace("olivia martin", "")
    assert "suggest" not in serialized.lower()


def test_tools_call_mixed_separators_work_without_tool_error():
    raw_text = "Name: Kevin Park\nEmail = kevin@example.com\nRole - Product Manager\nStatus: Pending"
    status, data = call_tool(raw_text)
    assert status == 200
    assert "error" not in data
    assert structured(data) == {
        "pairs": [
            {"key": "Name", "value": "Kevin Park"},
            {"key": "Email", "value": "kevin@example.com"},
            {"key": "Role", "value": "Product Manager"},
            {"key": "Status", "value": "Pending"},
        ],
        "missing_values": [],
        "errors": [],
    }


def test_three_repeated_calls_with_same_input_return_same_output():
    params = {"name": TOOL_NAME, "arguments": {"raw_text": "Name: Alice\nEmail = a@b.com\nPhone:"}}
    _, d1 = rpc("tools/call", params, 101)
    _, d2 = rpc("tools/call", params, 102)
    _, d3 = rpc("tools/call", params, 103)
    assert structured(d1) == structured(d2) == structured(d3)


def test_unknown_json_rpc_method_returns_error():
    _, data = rpc("unknown/method")
    assert "error" in data
    assert data["error"]["code"] == -32601


def test_invalid_tool_name_returns_error():
    status, data = rpc("tools/call", {"name": "wrong_tool", "arguments": {"raw_text": "Name: Alice"}})
    assert status == 200
    assert "error" in data
    assert data["error"]["code"] == -32602


def test_get_mcp_is_not_the_mcp_endpoint():
    try:
        request("GET", f"http://127.0.0.1:{port}/mcp")
    except urllib.error.HTTPError as exc:
        assert exc.code == 404
    else:
        raise AssertionError("GET /mcp should not accept MCP requests")
