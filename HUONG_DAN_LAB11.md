# Lab 11 — Guardrails, HITL và Responsible AI

Lab mô phỏng chatbot chăm sóc khách hàng của VinBank. Bạn sẽ theo dấu một câu hỏi ngân hàng qua từng lớp phòng thủ, xem lớp nào can thiệp và dùng dữ liệu đã ghi để giải thích kết quả.

## 1. Guardrails bảo vệ phần nào?

**Prompt injection** xảy ra khi nội dung đầu vào tìm cách đổi vai trò, sửa quy tắc hoặc yêu cầu model tiết lộ thông tin nội bộ. Injection gián tiếp nằm trong dữ liệu mà agent đọc, chẳng hạn email hoặc đoạn văn được truy xuất từ RAG. Email có thể là nguồn để tóm tắt. Hệ thống vẫn phải quyết định quyền hạn dựa trên chính sách và danh tính đã xác minh của người dùng.

**Phòng thủ nhiều lớp** đặt các quyết định ở nhiều điểm. Ví dụ, một câu hỏi có thể đúng chủ đề nhưng câu trả lời của model vẫn chứa thông tin nhận dạng cá nhân (PII). Input guardrail cho câu hỏi đi qua, còn output guardrail che trường nhạy cảm trước khi trả lời. Egress kiểm soát việc gửi dữ liệu đến dịch vụ hoặc công cụ bên ngoài.

```text
Yêu cầu → Rate limit → Input guardrail → Model → Output guardrail → Trả lời
   │                                                 │
   └──────────────── Audit & monitoring ─────────────┘

Hành động được đề xuất → Kiểm tra egress và quyền duyệt → Có thể thực thi
```

| Lớp | Quyết định trong lab | Mã nguồn |
| --- | --- | --- |
| Rate limit | Đếm theo từng `user_id` trong cửa sổ trượt. Mặc định cho qua tối đa 10 yêu cầu trong 60 giây. | [rate_limiter.py](src/assignment/rate_limiter.py) |
| Input guardrail | Chuẩn hóa Unicode và kiểm tra dấu hiệu ghi đè chỉ dẫn hoặc yêu cầu lộ bí mật. Câu hỏi phải thuộc phạm vi ngân hàng. | [input_guardrails.py](src/guardrails/input_guardrails.py) |
| Output guardrail | Kiểm tra nội dung model trả về. Che PII và bí mật bằng `[REDACTED]` trước khi người dùng thấy. | [output_guardrails.py](src/guardrails/output_guardrails.py) |
| Audit và monitoring | Audit lưu từng quyết định cùng mã yêu cầu và độ trễ. Monitoring tổng hợp số liệu và phát cảnh báo khi vượt ngưỡng. | [audit_log.py](src/assignment/audit_log.py), [monitoring.py](src/assignment/monitoring.py) |
| Egress | Chỉ cho phép địa chỉ HTTPS thuộc danh sách host nội bộ chính xác, với payload đạt kiểm tra dữ liệu nhạy cảm. | [pipeline.py](src/assignment/pipeline.py) |
| HITL | Chọn trả lời tự động, xếp hàng duyệt hoặc chuyển cho người có thẩm quyền. Hành động rủi ro cao luôn cần người xem xét. | [hitl.py](src/hitl/hitl.py) |

Regex phát hiện được những mẫu đã định nghĩa. Khả năng nhận dạng PII theo mẫu và phân loại chủ đề vẫn có giới hạn, nên hãy xem cả **false positive** (chặn nhầm) và **false negative** (bỏ sót). Che dữ liệu cũng khác với xác minh sự thật. Một câu trả lời qua bộ lọc PII vẫn có thể nêu sai lãi suất. Dữ liệu mẫu để so sánh nằm trong [pii_hallucination_samples.json](data/pii_hallucination_samples.json).

## 2. Chuẩn bị và chạy lần đầu

Mở terminal tại thư mục có `README.md`. Trên macOS hoặc Linux, dùng Python 3.11.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Trên Windows PowerShell, chạy `python -m venv .venv`, rồi `.\.venv\Scripts\Activate.ps1` và `python -m pip install -r requirements.txt`.

```bash
python src/main.py --part 2
python src/main.py --part 3 --offline
python src/hitl/hitl.py
```

Ba lệnh trên chạy với dữ liệu mẫu mà không cần API key. Chế độ `--offline` chạy callback và bộ lọc thực với câu trả lời mô phỏng của model. Dùng chế độ này để lặp lại thử nghiệm và kiểm tra lớp nào can thiệp.

### Demo trên trình duyệt

Từ thư mục Lab 11, chạy lệnh sau trên macOS hoặc Linux. Khi đã kích hoạt môi trường Python, bạn cũng có thể chạy `python scripts/demo_ui.py`.

```bash
.venv/bin/python scripts/demo_ui.py
```

Mở [http://127.0.0.1:8765/](http://127.0.0.1:8765/) rồi chọn một tình huống và chạy demo. Xem trạng thái theo từng lớp trong dấu vết xử lý. Một lớp bị bỏ qua nghĩa là luồng chưa đi đến lớp đó. Audit và metrics cho biết độ trễ, số lượt và quyết định trong lần chạy. Nhấn `Ctrl+C` trong terminal để dừng.

| Tình huống | Kết quả cần quan sát |
| --- | --- |
| Câu hỏi ngân hàng hoặc email chuyển khoản thông thường | Input guardrail cho qua. |
| Yêu cầu ngoài phạm vi | Input guardrail chặn trước model. |
| Phản hồi có PII mẫu | Output guardrail che trường nhạy cảm bằng `[REDACTED]`. |
| Gửi 15 yêu cầu liên tiếp | Rate limit cho qua 10 lượt và chặn 5 lượt của cùng người dùng mô phỏng. |
| Đích egress ngoài danh sách | Chính sách từ chối gửi dữ liệu. |
| Đề xuất chuyển tiền có confidence cao | HITL chuyển đề xuất cho người có thẩm quyền xem xét. |

Demo chạy bộ lọc Python của lab với câu trả lời model mô phỏng. Egress đánh giá địa chỉ đích và dữ liệu dự kiến gửi. HITL định tuyến hành động mô phỏng để người dùng thấy khi nào cần duyệt. Giao diện dùng dữ liệu mẫu và không cần API key.

## 3. Checkpoint 2 — Theo dấu đầu vào và đầu ra

1. Mở `detect_injection()` và `topic_filter()`. Đọc theo thứ tự callback gọi hai hàm. `ALLOW` cho phép xử lý tiếp. `BLOCK` trả phản hồi từ chối tại lớp input. Chuẩn hóa phục vụ so khớp, giúp tránh khác biệt do dấu tiếng Việt hoặc ký tự Unicode vô hình.
2. So sánh một câu hỏi về lãi suất, một câu lạc đề và trường hợp tóm tắt email chuyển khoản. Câu hỏi về lãi suất và yêu cầu tóm tắt nội dung ngân hàng thông thường cần qua lớp input. Nếu email chứa chỉ dẫn ghi đè quy tắc, lớp này phải chặn trước khi gọi model.
3. Mở `content_filter()`. Khi chuỗi có trường nhạy cảm, nhìn ba giá trị `safe`, `issues` và `redacted`. Plugin dùng chuỗi đã che khi trả lời. Khi đầu ra sạch, câu trả lời được giữ nguyên.

Bạn có thể thử ngay với email giả trong môi trường local.

```bash
python -c "import sys; sys.path.insert(0, 'src'); from guardrails.output_guardrails import content_filter; print(content_filter('Email hỗ trợ trong mẫu: hotro@example.test'))"
```

Kỳ vọng `safe` là `False` và email được thay bằng `[REDACTED]`. Thử lại với câu hỏi hoặc câu trả lời bình thường để đối chiếu.

## 4. Checkpoint 3 — Đọc bằng chứng của pipeline Blue

Mở `run_assignment_suite()` trong [pipeline.py](src/assignment/pipeline.py). Các plugin can thiệp ngay trong runtime. Audit và monitoring nhận kết quả của việc xử lý. Egress được kiểm tra riêng như một quyết định chính sách trước khi gửi dữ liệu tới một đích. Bộ kiểm thử chỉ đánh giá quyết định, không thực hiện chuyển tiền hoặc gửi payload tới các URL mẫu.

Sau khi chạy ngoại tuyến, đọc ba file trong [outputs/offline/](outputs/offline/).

| File | Cần xem |
| --- | --- |
| [results.json](outputs/offline/results.json) | `mode` ghi chế độ chạy. `safe_queries` nên qua hết. Trong các ca đầu vào rủi ro có ít nhất 5 ca bị can thiệp. `layer` ghi lớp can thiệp. `edge_cases` kiểm tra các trường hợp biên. Với nhóm rate limit mặc định, 15 lần gửi thì 10 qua và 5 bị chặn. |
| [audit_log.json](outputs/offline/audit_log.json) | Tìm bản ghi có `layer` là `input_guardrail`, rồi đối chiếu cặp input/output, `request_id` và `latency_ms`. Dữ liệu nhạy cảm được che trước khi lưu. |
| [metrics.json](outputs/offline/metrics.json) | `block_rate` bằng số yêu cầu bị can thiệp chia tổng yêu cầu. `rate_limit_hits` đếm riêng lượt bị giới hạn. Tỷ lệ ở đây mô tả bộ dữ liệu kiểm thử có chủ đích. |

`blocked: true` có nghĩa là một lớp đã can thiệp. Nếu `layer` là `output_guardrail`, model đã tạo câu trả lời và pipeline có thể gửi lại bản đã che. Nếu `layer` là `input_guardrail` hoặc `rate_limit`, yêu cầu dừng trước model.

Xem `egress_checks` để so sánh ba quyết định. Payload thường đi qua với đích nội bộ được phép. Đích ngoài danh sách hoặc dữ liệu nhạy cảm đều bị từ chối.

Kiểm tra file ngoại tuyến theo cùng schema của đề.

```bash
python -c "import json, jsonschema; from pathlib import Path; read = lambda p: json.loads(Path(p).read_text(encoding='utf-8')); jsonschema.validate(read('outputs/offline/results.json'), read('schemas/results.schema.json')); print('Schema hợp lệ')"
```

Để chạy với model Blue thật, tạo khóa tại [trang API Keys của OpenRouter](https://openrouter.ai/keys). Nếu chưa có `.env`, sao chép `.env.example` thành `.env`, rồi điền khóa vào dòng `OPENROUTER_API_KEY=` trong `.env`. Giữ khóa trên máy. Blue theo cấu hình của đề dùng `liquid/lfm-3-1.7b:free`.

Nếu OpenRouter trả HTTP 404 với lý do `Free model training violation (account settings)`, chính sách hiện tại đang loại nhà cung cấp của model miễn phí này. Nếu đồng ý cho nhà cung cấp có thể dùng prompt và đầu ra để huấn luyện, bạn có thể bật quyền tương ứng cho model miễn phí tại [Privacy Settings](https://openrouter.ai/settings/privacy) trước khi chạy lại. Chỉ dùng dữ liệu mô phỏng của lab cho lần chạy này. [Chính sách dữ liệu của nhà cung cấp](https://openrouter.ai/docs/guides/privacy/provider-logging).

```bash
python src/main.py --part 3
python -m pytest tests/public/test_results_contract.py -q
```

Lệnh chạy thật ghi vào `outputs/`. Kết quả mô phỏng nằm ở `outputs/offline/` để bạn có thể đối chiếu hai lần chạy. Bài yêu cầu artifact Blue ở đường dẫn `outputs/results.json`.

## 5. HITL — Giải thích khi nào cần người duyệt

| Điều kiện | Router trả về |
| --- | --- |
| Tác vụ thông thường, confidence ≥ 0,9 | `auto_send` |
| Tác vụ thông thường, 0,7 ≤ confidence < 0,9 | `queue_review` |
| Confidence < 0,7 hoặc không hợp lệ | `escalate` |
| Chuyển tiền, đóng tài khoản hoặc thao tác thuộc nhóm rủi ro cao | `escalate` ở mọi mức confidence |

Trong demo, hãy so sánh tình huống tra cứu số dư ở 0,95 với đề xuất chuyển tiền ở 0,98. Mức confidence là tín hiệu định tuyến. Quyền xem xét thao tác phát sinh từ chính sách rủi ro. Bản demo in quyết định và ba kịch bản duyệt. Nó mô phỏng định tuyến để đọc và thực hành.

- **Human-in-the-loop** giữ lệnh chuyển tiền chờ người có thẩm quyền duyệt nội dung.
- **Human-on-the-loop** cho phép giám sát vận hành và can thiệp khi metrics báo bất thường.
- **Human-as-tiebreaker** chuyển hai nguồn chính sách mâu thuẫn cho chuyên viên quyết định.

Khi cần người duyệt, hãy xác định người có thẩm quyền, dữ liệu tối thiểu họ cần thấy, cách xử lý hết hạn và các trường cần ghi audit. Với lệnh chuyển tiền, người duyệt cần nhìn số tiền và tài khoản đích đã che. Quyết định cần gắn với đúng nội dung đề xuất.

## 6. Tự kiểm và đối chiếu rubric

```bash
python -m pytest tests/smoke -q
python -m pytest tests/public -q
python scripts/grade.py --submission-dir . --out outputs/grade_report.json
```

Grader tạo `grade_report.json` và `lab_report.md`. Xem trường `technical_failure` và danh sách file bắt buộc để đọc trạng thái đóng gói. Bốn kiểm thử artifact sẽ hiện `skipped` nếu thiếu `outputs/results.json`. Có thể kiểm tra riêng schema của bản ngoại tuyến bằng lệnh ở mục 4.

### Còn thiếu gì để đủ bài nộp?

1. **Checkpoint 3 (Blue chạy thật).** Cấu hình `OPENROUTER_API_KEY` ở máy rồi thực hiện lệnh chạy thật ở mục 4 để sinh và kiểm tra `outputs/results.json`. Giữ file `.env` ngoài Git.
2. **Checkpoint 4 (bằng chứng Red).** Rubric yêu cầu `outputs/attack_results.json`. Mục này vẫn thiếu vì yêu cầu thiết kế prompt vượt guardrails để trích xuất bí mật. [RUBRIC.md](RUBRIC.md)
3. **Checkpoint 5 (tự kiểm và nộp).** Khi có đủ hai artifact chính thức, chạy lại grader, kiểm tra kết quả rồi nộp liên kết repo theo quy định. [SUBMISSION.md](SUBMISSION.md)
