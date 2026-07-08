from __future__ import annotations

from typing import Any

from analyse.prompts.json_schema_prompts import build_json_schema_instruction
from analyse.prompts.system_prompts import get_system_prompt
from analyse.utils.safe_json import safe_json_dumps


def build_report_prompt(context: dict[str, Any], schema: dict[str, Any] | None = None) -> str:
    schema_instruction = build_json_schema_instruction(schema)
    
    options = context.get("options") or {}
    pnl_context = options.get("pnl_context") or options.get("pnlContext")
    
    pnl_directive = ""
    if pnl_context:
        pnl_directive = f"""
CRITICAL PORTFOLIO ADVICE DIRECTIVE:
Người dùng đang nắm giữ cổ phiếu này trong danh mục. Bạn phải đưa ra phân tích và khuyến nghị dựa trên vị thế hiện tại của họ:
{build_pnl_context_section(pnl_context)}

LƯU Ý ĐƠN VỊ TÀI CHÍNH QUAN TRỌNG: Tất cả các số tài chính trong JSON CONTEXT (như doanh thu/revenue, lợi nhuận/profit_after_tax, nợ/total_liabilities, vốn chủ/equity, tài sản/total_assets, v.v.) đều có đơn vị gốc là TRIỆU ĐỒNG (million VND). Khi viết phân tích, bạn PHẢI đổi sang TỶ ĐỒNG (billion VND) bằng cách chia các số này cho 1,000. Ví dụ: doanh thu 12480000 nghĩa là 12,480 tỷ VND. Tuyệt đối không được giữ nguyên đơn vị triệu đồng mà chia cho 1 tỷ dẫn đến ghi nhận doanh thu/lợi nhuận 0.0 tỷ đồng.

Yêu cầu bắt buộc: Mảng `system_decision.reasons` phải chứa đúng 5 chuỗi (5 lý do) tương ứng với 5 tiêu chí sau và bắt đầu chính xác bằng các tiền tố dưới đây. Mỗi lý do/tiêu chí phải cực kỳ chi tiết, thuyết phục cao, BẮT BUỘC phải kèm theo các con số, số liệu cụ thể (như tỷ lệ %, doanh thu, lợi nhuận, P/E, P/B, giá vốn, giá hiện tại, v.v. đã được xác thực từ JSON CONTEXT) và trích nguồn tham khảo trực tiếp (ví dụ: theo BCTC Q3/2025, nguồn CafeF, nguồn Vietstock) để người dùng có thể tự check lại. Tuyệt đối không viết nhận định chung chung, suông và thiếu số liệu dẫn chứng:
1. "VỊ THẾ GIÁ VỐN: <nêu rõ các con số như giá vốn trung bình, giá đóng cửa hiện tại, số lượng nắm giữ, tỷ lệ lãi/lỗ % và giá trị lãi/lỗ VND thực tế từ danh mục được cung cấp trong CONTEXT, đánh giá mức độ rủi ro vị thế hiện tại>"
2. "SỨC KHỎE TÀI CHÍNH: <tóm tắt chi tiết với các số liệu cụ thể về doanh thu, lợi nhuận sau thuế, nợ vay hoặc các biên tài chính của kỳ báo cáo gần nhất trong CONTEXT kèm nguồn và thời gian như BCTC Q1/2026 nguồn Vietstock Finance/CafeF>"
3. "ĐỊNH GIÁ & ĐỐI THỦ: <nêu cụ thể chỉ số định giá P/E, P/B, ROE hiện tại của cổ phiếu và so sánh trực tiếp bằng số liệu cụ thể với trung bình ngành hoặc các đối thủ cạnh tranh cùng ngành được liệt kê trong CONTEXT kèm nguồn tham khảo>"
4. "XU HƯỚNG & THỊ TRƯỜNG: <nêu cụ thể phần trăm thay đổi giá gần đây, khối lượng giao dịch hoặc xu hướng của VN-Index với các con số cụ thể từ bối cảnh thị trường trong CONTEXT>"
5. "NGUYÊN TẮC HÀNH ĐỘNG: <khuyến nghị hành động cụ thể giữ/bán/mua kèm theo số liệu cụ thể về vùng giá chốt lời Target và cắt lỗ Stop-loss hoặc tỷ trọng giải ngân khuyến nghị dựa trên các mức hỗ trợ/kháng cự có trong CONTEXT>"
""".strip()

    return f"""{get_system_prompt()}

OUTPUT REQUIREMENTS:
{schema_instruction}

{pnl_directive}

MANDATORY OUTPUT REQUIREMENTS:

1. scenarios:
   Return exactly 3 scenarios:
   - Tích cực
   - Cơ sở
   - Thận trọng

   Each scenario must include:
   - scenario
   - probability_pct
   - time_horizon
   - condition
   - expected_behavior
   - supporting_signals
   - invalidation_signals
   - risk_note

2. checklist:
   Return at least 5 checklist items.
   Each item must include:
   - label
   - status
   - note
   - source_basis

3. action_plan:
   Return:
   - at least 2 short_term actions
   - at least 2 medium_term actions
   - at least 3 watch_points
   - at least 3 risk_management items

4. evidence_pool:
   Với mỗi lý do trong `system_decision.reasons` hoặc phân tích của bạn, bạn PHẢI populate `evidence_pool[]` với các evidence tương ứng có số liệu và nguồn rõ ràng:
   - metric_name: tên chỉ số/số liệu cụ thể (VD: 'P/E', 'Doanh thu Q1/2026', 'Tin tức: HPG báo lãi tăng 40%')
   - value: giá trị chính xác từ JSON CONTEXT (không được bịa, ví dụ: 12480 hoặc "3,200 tỷ")
   - unit: đơn vị (VND, %, tỷ VND, cổ phiếu...) hoặc null
   - source: một trong {{history_bctc, history_market, history_peer, history_hose, cafef_news, vietstock_news, google_news, backend_price}}
   - source_url: BẮT BUỘC nếu source là cafef_news, vietstock_news, hoặc google_news; lấy chính xác từ trường url trong external_research.items của JSON CONTEXT.
   - published_at: ISO date của số liệu/bài viết (hoặc null nếu không có).
   Tuyệt đối không trả về evidence chung chung (VD "theo báo cáo" mà không có số liệu). Mọi evidence phải có giá trị cụ thể.

5. Do not output empty arrays for these sections.

6. Do not use "Chưa xác minh", "Chưa xác định", "Không có dữ liệu", "Không đủ dữ liệu", "N/A", "unknown", "null", or "undefined" as qualitative content.

7. If numeric values are missing, set numeric fields to null and provide a specific limitation note.

8. Always produce a useful forecast-oriented report from the available evidence.

JSON CONTEXT:
{safe_json_dumps(context)}
""".strip()


def build_pnl_context_section(pnl_context: dict[str, Any] | None) -> str:
    """
    Tạo phần context P&L để inject vào prompt LLM khi phân tích holdings.

    Được gọi bởi HoldingsAdviceService — không ảnh hưởng đến build_report_prompt cũ.

    Args:
        pnl_context: dict chứa thông tin holdings (average_cost, quantity, unrealized_pnl_pct, ...)

    Returns:
        Chuỗi Markdown mô tả vị thế đầu tư, hoặc "" nếu không có context.
    """
    if not pnl_context or not isinstance(pnl_context, dict):
        return ""

    average_cost = pnl_context.get("average_cost")
    quantity = pnl_context.get("quantity")
    unrealized_pnl = pnl_context.get("unrealized_pnl")
    unrealized_pnl_pct = pnl_context.get("unrealized_pnl_pct")
    status = pnl_context.get("status")
    company_name = pnl_context.get("company_name", "")

    # Format số
    cost_str = f"{average_cost:,.0f}" if average_cost is not None else "N/A"
    qty_str = f"{quantity:,}" if quantity is not None else "N/A"

    if unrealized_pnl is not None and unrealized_pnl_pct is not None:
        pnl_str = f"{unrealized_pnl:+,.0f} VND ({unrealized_pnl_pct:+.2f}%)"
        status_str = "đang lãi" if status == "PROFIT" else "đang lỗ"
    else:
        pnl_str = "Chưa có dữ liệu giá"
        status_str = ""

    company_line = f" ({company_name})" if company_name else ""

    lines = [
        "## DANH MỤC NHÀ ĐẦU TƯ" + company_line,
        f"- Giá vốn trung bình: {cost_str} VND/cổ phiếu",
        f"- Số lượng nắm giữ: {qty_str} cổ phiếu",
    ]

    if unrealized_pnl is not None:
        lines.append(
            f"- Lãi/lỗ chưa thực hiện: {pnl_str} — {status_str}"
        )
        lines.append(
            "→ Dựa trên vị thế trên, khuyến nghị: giữ / mua thêm / chốt lời / cắt lỗ? "
            "Cung cấp ngưỡng giá cụ thể (target price, stop-loss)."
        )

    return "\n".join(lines)

