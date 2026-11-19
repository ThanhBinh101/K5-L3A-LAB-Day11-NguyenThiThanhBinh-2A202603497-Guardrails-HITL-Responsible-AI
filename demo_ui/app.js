const get = (id) => document.getElementById(id);

const outcomes = {
  allowed: "Cho qua",
  blocked: "Đã chặn",
  redacted: "Đã che dữ liệu",
  review: "Cần người duyệt",
};
const statuses = {
  pass: "Qua",
  block: "Chặn",
  review: "Cần duyệt",
  skip: "Bỏ qua",
  info: "Thông tin",
};
const groups = {
  banking: "Blue · luồng thông thường",
  external: "Input guardrail",
  off_topic: "Input guardrail",
  redaction: "Output guardrail",
  rate_limit: "Rate limiter",
  egress: "Egress policy",
  hitl: "Human-in-the-loop",
};

let activeScenario;
let pendingRun;

function element(tag, text, className) {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}

function setFeedback(message, error = false) {
  const feedback = get("feedback");
  feedback.textContent = message;
  feedback.classList.toggle("error", error);
  feedback.hidden = !message;
}

function openScenario(scenario, button) {
  pendingRun?.abort();
  pendingRun = null;
  activeScenario = scenario;
  for (const option of get("scenario-list").querySelectorAll("button")) {
    option.setAttribute("aria-pressed", String(option === button));
  }
  get("case-title").textContent = scenario.label;
  get("case-description").textContent = scenario.description;
  get("input-label").textContent = scenario.input_label || "Đầu vào";
  get("input").value = scenario.input;
  get("input").disabled = false;
  setBusy(false);
  get("result").hidden = true;
  get("verdict").hidden = true;
  setFeedback("Chạy kịch bản để xem quyết định tại từng lớp.");
}

function setBusy(busy) {
  get("run").disabled = busy;
  get("run").textContent = busy ? "Đang chạy…" : "Chạy kịch bản";
  get("reset").disabled = busy;
}

function showResult(data) {
  const verdict = get("verdict");
  verdict.textContent = outcomes[data.outcome];
  verdict.dataset.outcome = data.outcome;
  verdict.hidden = false;
  get("reply").textContent = data.reply;

  const entries = data.trace.map((step) => {
    const row = element("li", "", "trace-entry");
    row.dataset.status = step.status;
    const tick = element("span", "", "trace-node");
    tick.setAttribute("aria-hidden", "true");
    const body = element("div", "", "trace-body");
    const heading = element("div", "", "trace-title");
    heading.append(element("strong", step.label), element("span", statuses[step.status]));
    body.append(heading, element("p", step.detail));
    row.append(tick, body);
    return row;
  });
  get("trace").replaceChildren(...entries);

  const rate = data.rate_limit;
  get("burst").hidden = !rate;
  if (rate) {
    get("passed-count").textContent = `${rate.passed} lượt trong hạn mức`;
    get("blocked-count").textContent = `${rate.blocked} lượt bị giới hạn`;
    get("passed-bar").style.width = `${(rate.passed / rate.sent) * 100}%`;
    get("burst-rule").textContent = `${rate.sent} lượt gửi từ cùng một người dùng. Giới hạn ${rate.max_requests} lượt trong ${rate.window_seconds} giây.`;
  }

  const summary = [
    ["Lớp ghi nhận", data.audit.layer || "Không có can thiệp"],
    ["Độ trễ yêu cầu cuối", `${data.audit.latency_ms.toFixed(2)} ms`],
    ["Tổng yêu cầu", data.metrics.total_requests],
    ["Yêu cầu bị can thiệp", data.metrics.blocked_requests],
  ];
  get("audit").replaceChildren(...summary.flatMap(([label, value]) => [
    element("dt", label), element("dd", value),
  ]));
  setFeedback("");
  get("result").hidden = false;
}

async function runScenario() {
  if (!activeScenario || pendingRun) return;
  const controller = new AbortController();
  pendingRun = controller;
  setBusy(true);
  get("result").hidden = true;
  get("verdict").hidden = true;
  setFeedback("Đang xử lý yêu cầu…");
  try {
    const response = await fetch("/api/run", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({scenario: activeScenario.id, input: get("input").value}),
      signal: controller.signal,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Demo chưa xử lý được yêu cầu.");
    if (pendingRun === controller) showResult(data);
  } catch (error) {
    if (pendingRun === controller && error.name !== "AbortError") {
      const message = error instanceof TypeError
        ? "Mất kết nối với demo cục bộ. Hãy kiểm tra terminal rồi thử lại."
        : error.message;
      setFeedback(message, true);
    }
  } finally {
    if (pendingRun === controller) {
      pendingRun = null;
      setBusy(false);
    }
  }
}

get("experiment").addEventListener("submit", (event) => {
  event.preventDefault();
  runScenario();
});
get("reset").addEventListener("click", () => {
  get("input").value = activeScenario.input;
  get("input").focus();
});

async function boot() {
  const list = get("scenario-list");
  try {
    const response = await fetch("/api/scenarios");
    if (!response.ok) throw new Error("Không tải được kịch bản.");
    const {scenarios} = await response.json();
    const buttons = scenarios.map((scenario) => {
      const button = element("button", "", "scenario");
      button.type = "button";
      button.setAttribute("aria-pressed", "false");
      button.append(element("strong", scenario.label), element("span", groups[scenario.id]));
      button.addEventListener("click", () => openScenario(scenario, button));
      return button;
    });
    list.replaceChildren(...buttons);
    openScenario(scenarios[0], buttons[0]);
    await runScenario();
  } catch {
    list.replaceChildren(element("p", "Không kết nối được demo cục bộ.", "muted"));
    get("case-description").textContent = "Khởi động máy chủ demo rồi mở lại trang.";
    setFeedback("Hãy chạy python scripts/demo_ui.py từ thư mục Lab 11.", true);
  }
}

boot();
