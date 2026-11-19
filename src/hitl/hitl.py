"""
Lab 11 — Optional enrichment: Human-in-the-Loop Design
  (Không chấm — tham khảo. Tóm tắt nộp do scripts/grade.py tự sinh,
   không viết report/*.md tay.)
  - Confidence Router
  - 3 HITL decision points
"""
from dataclasses import dataclass


HIGH_RISK_ACTIONS = [
    "transfer_money",
    "close_account",
    "change_password",
    "delete_data",
    "update_personal_info",
]


@dataclass
class RoutingDecision:
    """Result of the confidence router."""
    action: str          # "auto_send", "queue_review", "escalate"
    confidence: float
    reason: str
    priority: str        # "low", "normal", "high"
    requires_human: bool


class ConfidenceRouter:
    """Route agent responses based on confidence and risk level.

    Thresholds:
        HIGH:   confidence >= 0.9 -> auto-send
        MEDIUM: 0.7 <= confidence < 0.9 -> queue for review
        LOW:    confidence < 0.7 -> escalate to human

    High-risk actions always escalate regardless of confidence.
    """

    HIGH_THRESHOLD = 0.9
    MEDIUM_THRESHOLD = 0.7

    def route(self, response: str, confidence: float,
              action_type: str = "general") -> RoutingDecision:
        """Route a response based on confidence score and action type.

        Args:
            response: The proposed text. Routing uses its risk and confidence metadata.
            confidence: Confidence score between 0.0 and 1.0
            action_type: Type of action (e.g., "general", "transfer_money")

        Returns:
            RoutingDecision with routing action and metadata
        """
        action_type = action_type.strip().casefold()
        if action_type in HIGH_RISK_ACTIONS:
            return RoutingDecision(
                "escalate", confidence, f"High-risk action: {action_type}", "high", True
            )

        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0.0 <= confidence <= 1.0
        ):
            return RoutingDecision("escalate", confidence, "Invalid confidence", "high", True)

        if confidence >= self.HIGH_THRESHOLD:
            return RoutingDecision("auto_send", confidence, "High confidence", "low", False)

        if confidence >= self.MEDIUM_THRESHOLD:
            return RoutingDecision(
                "queue_review", confidence, "Medium confidence needs review", "normal", True
            )

        return RoutingDecision("escalate", confidence, "Low confidence", "high", True)


hitl_decision_points = [
    {
        "id": 1,
        "name": "Duyệt trước khi chuyển tiền",
        "trigger": "Agent đề xuất thao tác chuyển tiền ở bất kỳ mức confidence nào.",
        "hitl_model": "human-in-the-loop",
        "context_needed": "Ý định đã xác minh, số tiền, loại tiền, tài khoản đích đã che và kết quả kiểm tra egress.",
        "example": "Agent chuẩn bị lệnh chuyển 5 triệu đồng cho người nhận mới.",
        "approval_path": (
            "Giữ lệnh đến khi người có thẩm quyền duyệt chính xác nội dung đề xuất. "
            "Kiểm tra lại egress trước khi thực thi. Từ chối hoặc hết hạn thì hủy lệnh và ghi trạng thái."
        ),
        "audit_fields": (
            "correlation_id, intent, tham chiếu đến nội dung lệnh, reviewer_id, approval_id, "
            "quyết định và thời điểm."
        ),
    },
    {
        "id": 2,
        "name": "Giám sát chất lượng tự động trả lời",
        "trigger": "Tỷ lệ chặn hoặc che thông tin tăng vượt ngưỡng trong cửa sổ theo dõi.",
        "hitl_model": "human-on-the-loop",
        "context_needed": "Chỉ số theo thời gian, phiên bản policy, lớp chặn và mẫu đã che dữ liệu nhạy cảm.",
        "example": "Tỷ lệ che nội dung tăng sau khi cập nhật nguồn dữ liệu cho thẻ tín dụng.",
        "approval_path": (
            "Tạm dừng trả lời tự động cho luồng bị ảnh hưởng khi cảnh báo kích hoạt. "
            "Người trực duyệt mở lại sau khi kiểm tra. Nếu từ chối hoặc hết hạn, giữ trạng thái tạm dừng."
        ),
        "audit_fields": (
            "correlation_id, alert_id, policy_version, chỉ số, lý do, phạm vi tạm dừng, "
            "reviewer_id, quyết định và thời điểm."
        ),
    },
    {
        "id": 3,
        "name": "Xử lý nguồn chính sách mâu thuẫn",
        "trigger": "Hai nguồn chính thức đưa ra điều kiện khác nhau cho cùng một sản phẩm.",
        "hitl_model": "human-as-tiebreaker",
        "context_needed": "Câu hỏi đã che dữ liệu nhạy cảm, đoạn trích, mã phiên bản và thời điểm hiệu lực của từng nguồn.",
        "example": "Hai tài liệu nêu mức phí khác nhau cho tất toán khoản vay trước hạn.",
        "approval_path": (
            "Chuyên viên chọn nguồn đang có hiệu lực và duyệt bản trả lời có dẫn nguồn. "
            "Nếu từ chối hoặc hết hạn, mở yêu cầu xác minh và báo khách đang chờ kiểm tra."
        ),
        "audit_fields": (
            "correlation_id, intent, source_ids, phiên bản, tham chiếu bản trả lời đề xuất, "
            "reviewer_id, quyết định và thời điểm."
        ),
    },
]


# ============================================================
# Quick tests
# ============================================================

def test_confidence_router():
    """Test ConfidenceRouter with sample scenarios."""
    router = ConfidenceRouter()

    test_cases = [
        ("Balance inquiry", 0.95, "general"),
        ("Interest rate question", 0.82, "general"),
        ("Ambiguous request", 0.55, "general"),
        ("Transfer $50,000", 0.98, "transfer_money"),
        ("Close my account", 0.91, "close_account"),
    ]

    print("Testing ConfidenceRouter:")
    print("=" * 80)
    print(f"{'Scenario':<25} {'Conf':<6} {'Action Type':<18} {'Decision':<15} {'Priority':<10} {'Human?'}")
    print("-" * 80)

    for scenario, conf, action_type in test_cases:
        decision = router.route(scenario, conf, action_type)
        print(
            f"{scenario:<25} {conf:<6.2f} {action_type:<18} "
            f"{decision.action:<15} {decision.priority:<10} "
            f"{'Yes' if decision.requires_human else 'No'}"
        )

    print("=" * 80)


def test_hitl_points():
    """Display HITL decision points."""
    print("\nHITL Decision Points:")
    print("=" * 60)
    for point in hitl_decision_points:
        print(f"\n  Decision Point #{point['id']}: {point['name']}")
        print(f"    Trigger:  {point['trigger']}")
        print(f"    Model:    {point['hitl_model']}")
        print(f"    Context:  {point['context_needed']}")
        print(f"    Example:  {point['example']}")
        print(f"    Approval: {point['approval_path']}")
        print(f"    Audit:    {point['audit_fields']}")
    print("\n" + "=" * 60)


if __name__ == "__main__":
    test_confidence_router()
    test_hitl_points()
