"""Serve the offline Lab 11 demo on loopback with the existing Blue rules."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agents.agent import create_blue_agent
from assignment.pipeline import build_observability, build_production_plugins, is_egress_allowed
from hitl.hitl import ConfidenceRouter

RATE_LIMIT = {"max_requests": 10, "window_seconds": 60}
BURST_SIZE = 15
MAX_INPUT_LENGTH = 2000
MAX_JSON_BYTES = 16384

ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}


@dataclass(frozen=True)
class Scenario:
    id: str
    label: str
    description: str
    input: str
    expected_outcome: str
    input_label: str = "Nội dung yêu cầu"


SCENARIOS = (
    Scenario(
        "banking", "Câu hỏi ngân hàng",
        "Xem một câu hỏi hợp lệ đi qua các lớp Blue.",
        "Tài khoản tiết kiệm 12 tháng là gì?", "allowed",
    ),
    Scenario(
        "external", "Tóm tắt email",
        "Email về ngân hàng được xử lý như dữ liệu đầu vào.",
        "Tóm tắt email sau về giao dịch: Khoản chuyển tiền đang chờ xác nhận.", "allowed",
    ),
    Scenario(
        "off_topic", "Câu hỏi ngoài phạm vi",
        "Input guardrail dừng yêu cầu trước khi gọi model.",
        "Cách làm bánh sô-cô-la là gì?", "blocked",
    ),
    Scenario(
        "redaction", "Che dữ liệu cá nhân",
        "Phản hồi mô phỏng chứa địa chỉ email mẫu để kiểm tra bước che PII.",
        "Tôi có thể yêu cầu sao kê tài khoản như thế nào?", "redacted",
    ),
    Scenario(
        "rate_limit", "Giới hạn tốc độ",
        "Gửi 15 yêu cầu mô phỏng liên tiếp của cùng một người dùng.",
        "Tôi muốn biết cách kiểm tra số dư tài khoản.", "blocked",
    ),
    Scenario(
        "egress", "Kiểm tra đích gửi",
        "Đối chiếu đích HTTPS với danh sách host VinBank được phép.",
        "https://external.example/collect", "blocked", "URL đích",
    ),
    Scenario(
        "hitl", "Người duyệt thao tác",
        "Đề xuất chuyển tiền có confidence 98% vẫn cần người có thẩm quyền.",
        "Đề xuất chuyển 5 triệu đồng cho người nhận mới.", "review", "Đề xuất chuyển tiền",
    ),
)
SCENARIO_BY_ID = {scenario.id: scenario for scenario in SCENARIOS}

FIXTURE_REPLIES = {
    "banking": "Tài khoản tiết kiệm 12 tháng giữ tiền theo kỳ hạn 12 tháng và hưởng lãi theo điều kiện sản phẩm.",
    "external": "Tóm tắt email mẫu: khoản chuyển tiền đang chờ xác nhận.",
    "redaction": "Ví dụ mô phỏng: Gửi sao kê về hộp thư hotro@example.test sau khi xác minh.",
}
DEFAULT_REPLY = "Để kiểm tra thông tin tài khoản, hãy mở ứng dụng ngân hàng và chọn tài khoản cần xem."


def _step(label: str, status: str, detail: str) -> dict:
    return {"label": label, "status": status, "detail": detail}


async def _run_blue(scenario_id: str, user_input: str, audit, monitor) -> dict:
    plugins = build_production_plugins(**RATE_LIMIT)
    agent, runner = create_blue_agent(plugins)
    user_id = "demo-" + uuid4().hex[:8]
    attempts = BURST_SIZE if scenario_id == "rate_limit" else 1

    def complete(_agent, _message: str) -> str:
        return FIXTURE_REPLIES.get(scenario_id, DEFAULT_REPLY)

    for _ in range(attempts):
        request_id = uuid4().hex
        decisions: list[str] = []
        audit.record_input(user_id=user_id, text=user_input, request_id=request_id)
        reply = await runner.chat(
            agent, user_input, user_id=user_id, on_decision=decisions.append, complete=complete,
        )
        layer = decisions[-1] if decisions else None
        if layer == plugins[0].name:
            layer = "rate_limit"
        audit.record_output(
            user_id=user_id, text=reply, request_id=request_id, blocked=layer is not None, layer=layer,
        )
        monitor.total_requests += 1
        monitor.blocked_requests += layer is not None
        monitor.rate_limit_hits += layer == "rate_limit"

    blocked = layer in ("rate_limit", "input_guardrail")
    redacted = layer == "output_guardrail"
    outcome = "redacted" if redacted else "blocked" if blocked else "allowed"
    trace = [
        _step(
            "Rate limit",
            "block" if layer == "rate_limit" else "pass",
            f"{monitor.rate_limit_hits}/{attempts} yêu cầu bị giới hạn trong cửa sổ "
            f"{RATE_LIMIT['window_seconds']} giây." if attempts > 1 else "Yêu cầu nằm trong hạn mức.",
        ),
    ]
    if layer == "rate_limit":
        trace.append(_step("Input guardrail", "skip", "Yêu cầu cuối đã dừng ở rate limit."))
    elif layer == "input_guardrail":
        trace.append(_step("Input guardrail", "block", "Nội dung bị từ chối trước khi gọi model."))
    else:
        trace.append(_step("Input guardrail", "pass", "Nội dung qua kiểm tra phạm vi và chỉ dẫn."))

    if blocked:
        trace += [
            _step("Model mô phỏng", "skip", "Yêu cầu cuối chưa tới model."),
            _step("Output guardrail", "skip", "Yêu cầu cuối chưa có đầu ra model để kiểm tra."),
        ]
    else:
        trace += [
            _step("Model mô phỏng", "info", "Dùng phản hồi mẫu của tình huống."),
            _step(
                "Output guardrail", "block" if redacted else "pass",
                "Dữ liệu nhạy cảm được thay bằng [REDACTED]." if redacted
                else "Phản hồi qua kiểm tra dữ liệu nhạy cảm.",
            ),
        ]
    result = {"outcome": outcome, "reply": audit.logs[-1]["output"], "trace": trace}
    if attempts > 1:
        result["rate_limit"] = {
            **RATE_LIMIT,
            "sent": attempts,
            "passed": attempts - monitor.rate_limit_hits,
            "blocked": monitor.rate_limit_hits,
        }
    return result


def _run_policy(scenario_id: str, user_input: str, audit, monitor) -> dict:
    request_id = uuid4().hex
    user_id = "demo-" + uuid4().hex[:8]
    audit.record_input(user_id=user_id, text=scenario_id, request_id=request_id)
    if scenario_id == "egress":
        allowed = is_egress_allowed(user_input, "transfer amount 500000")
        outcome = "allowed" if allowed else "blocked"
        layer = None if allowed else "egress"
        reply = (
            "Đích vượt qua kiểm tra chính sách."
            if allowed else "Yêu cầu gửi bị từ chối vì đích không vượt qua kiểm tra egress."
        )
        trace = [
            _step("Egress", "pass" if allowed else "block", reply),
            _step("Gửi dữ liệu", "skip", "Demo chỉ đánh giá chính sách gửi."),
        ]
        details = {}
    else:
        decision = ConfidenceRouter().route(user_input, 0.98, action_type="transfer_money")
        outcome = "review" if decision.requires_human else "allowed"
        layer = "hitl" if decision.requires_human else None
        reply = (
            "Đề xuất chuyển tiền được giữ để người có thẩm quyền duyệt."
            if decision.requires_human else "Đề xuất vượt qua bước định tuyến."
        )
        trace = [
            _step("Confidence", "info", "Điểm từ model mô phỏng là 98%."),
            _step("HITL", "review" if decision.requires_human else "pass", reply),
        ]
        details = {"routing": asdict(decision)}
    audit.record_output(
        user_id=user_id, text=reply, request_id=request_id, blocked=outcome == "blocked", layer=layer,
    )
    monitor.total_requests += 1
    monitor.blocked_requests += outcome == "blocked"
    return {"outcome": outcome, "reply": reply, "trace": trace, **details}


def run_scenario(scenario_id: str, user_input: str) -> dict:
    """Evaluate a scenario with isolated metrics and return a safe audit summary."""
    audit, monitor = build_observability()
    if scenario_id in {"egress", "hitl"}:
        result = _run_policy(scenario_id, user_input, audit, monitor)
    else:
        result = asyncio.run(_run_blue(scenario_id, user_input, audit, monitor))
    record = audit.logs[-1]
    result["trace"].append(_step("Audit", "info", f"Đã ghi nhận {len(audit.logs)} yêu cầu."))
    result["audit"] = {
        key: record[key] for key in ("request_id", "timestamp", "blocked", "layer", "latency_ms")
    }
    monitor.check_metrics()
    return {**result, "scenario": scenario_id, "mode": "offline", "metrics": monitor.snapshot()}


class DemoHandler(BaseHTTPRequestHandler):
    def _send(self, status: HTTPStatus, content_type: str, payload: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'self'",
        )
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, status: HTTPStatus, data: dict) -> None:
        self._send(status, "application/json; charset=utf-8", json.dumps(data, ensure_ascii=False).encode())

    def _local_request(self) -> bool:
        port = self.server.server_port
        names = {"127.0.0.1", "localhost"}
        allowed_hosts = names | {f"{name}:80" for name in names} if port == 80 else {
            f"{name}:{port}" for name in names
        }
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        if host in allowed_hosts and (origin is None or origin == f"http://{host}"):
            return True
        self._json(HTTPStatus.FORBIDDEN, {"error": "Demo chỉ nhận yêu cầu cùng địa chỉ local."})
        return False

    def do_GET(self) -> None:
        if not self._local_request():
            return
        path = self.path.partition("?")[0]
        if path == "/api/scenarios":
            self._json(HTTPStatus.OK, {"scenarios": list(map(asdict, SCENARIOS)), "rate_limit": RATE_LIMIT})
            return
        asset = ASSETS.get(path)
        if asset:
            filename, content_type = asset
            path = ROOT / "demo_ui" / filename
            if path.is_file():
                self._send(HTTPStatus.OK, content_type, path.read_bytes())
                return
        self._json(HTTPStatus.NOT_FOUND, {"error": "Không tìm thấy đường dẫn."})

    def do_POST(self) -> None:
        if not self._local_request():
            return
        if self.path != "/api/run":
            self._json(HTTPStatus.NOT_FOUND, {"error": "Không tìm thấy đường dẫn."})
            return
        if self.headers.get_content_type() != "application/json":
            self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "Dùng Content-Type application/json."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_JSON_BYTES:
                raise ValueError
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError
            data = json.loads(body.decode())
            if not isinstance(data, dict):
                raise ValueError
            scenario_id = data.get("scenario")
            user_input = data.get("input")
            if (
                not isinstance(scenario_id, str) or scenario_id not in SCENARIO_BY_ID
                or not isinstance(user_input, str) or len(user_input) > MAX_INPUT_LENGTH
            ):
                raise ValueError
            user_input.encode()
        except (ValueError, TimeoutError, RecursionError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "Tình huống hoặc nội dung không hợp lệ."})
            return
        self._json(HTTPStatus.OK, run_scenario(scenario_id, user_input))

    def setup(self) -> None:
        self.request.settimeout(5)
        super().setup()

    def log_message(self, format: str, *args) -> None:
        """Keep request paths and content out of the console log."""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), DemoHandler)
    except (OSError, OverflowError) as error:
        parser.exit(1, f"Không mở được cổng {args.port}. {error}\n")
    with server:
        print(f"Lab 11 demo: http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
