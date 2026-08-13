import json
from io import BytesIO
from unittest.mock import patch

from v5.dashboard import Handler


def _handler(path):
    handler=object.__new__(Handler);handler.path=path;handler.wfile=BytesIO();handler.headers={};handler.request_version="HTTP/1.1";handler.command="GET";handler.responses=Handler.responses
    handler.send_response=lambda status: setattr(handler,"status",status)
    handler.send_header=lambda *_: None
    handler.end_headers=lambda: None
    return handler


def test_dashboard_api_returns_explicit_503_on_fact_validation_failure():
    handler=_handler("/api/read-model")
    with patch("v5.dashboard.V5ReadOnlySources.build",side_effect=ValueError("lineage mismatch")):
        handler.do_GET()
    payload=json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert handler.status==503 and payload["status"]=="DATA_VALIDATION_FAILED"
    assert "lineage mismatch" not in payload["message"]


def test_dashboard_html_returns_explicit_503_without_stale_decision():
    handler=_handler("/")
    with patch("v5.dashboard.V5ReadOnlySources.build",side_effect=ValueError("lineage mismatch")):
        handler.do_GET()
    page=handler.wfile.getvalue().decode("utf-8")
    assert handler.status==503 and "数据校验失败" in page and "不会回退旧数据" in page
