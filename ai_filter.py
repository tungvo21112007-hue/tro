"""
ai_filter.py – Phân tích & chuẩn hóa tin cho thuê Đà Nẵng bằng Gemini 2.5 Flash.
Trả về structured output qua Pydantic response_schema.
"""

import logging
import os
from typing import Any, Dict, Optional

from google import genai
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

DANANG_DISTRICTS = [
    "Hải Châu",
    "Thanh Khê",
    "Sơn Trà",
    "Ngũ Hành Sơn",
    "Liên Chiểu",
    "Cẩm Lệ",
    "Hòa Vang",
]


# ── Pydantic schema cho structured output ────────────────────────────
class RentalAnalysis(BaseModel):
    is_valid_rental: bool = Field(
        description=(
            "True nếu bài viết là tin CHO THUÊ phòng trọ / căn hộ / nhà thực sự "
            "(có giá, có địa chỉ, người đăng là chủ nhà hoặc môi giới). "
            "False nếu là tin TÌM PHÒNG, pass đồ, quảng cáo dịch vụ, tuyển dụng, "
            "bán hàng, hoặc nội dung không liên quan cho thuê."
        ),
    )
    is_spam: bool = Field(
        description=(
            "True nếu giá ảo (1đ, 1k, 0đ, 999đ), bài copy-paste câu tương tác, "
            "bài chỉ có ảnh không nội dung, hoặc tin lừa đảo rõ ràng. "
            "False nếu bài viết có thông tin cho thuê hợp lý."
        ),
    )
    price_vnd: Optional[int] = Field(
        None,
        description=(
            "Giá thuê HÀNG THÁNG quy đổi ra đơn vị VNĐ (số nguyên). "
            "Ví dụ: '2tr5' → 2500000, '3.5 triệu' → 3500000, '800k' → 800000. "
            "None nếu không xác định được giá hoặc giá ghi là 'thỏa thuận'."
        ),
    )
    district: Optional[str] = Field(
        None,
        description=(
            "Tên quận/huyện tại Đà Nẵng, chuẩn hóa chính xác về một trong: "
            + ", ".join(DANANG_DISTRICTS)
            + ". None nếu không xác định được khu vực."
        ),
    )
    room_type: Optional[str] = Field(
        None,
        description=(
            "Loại hình cho thuê, chỉ trả về một trong ba giá trị: "
            "'Phòng trọ', 'Căn hộ/CCMN', hoặc 'Nhà nguyên căn'. "
            "None nếu không xác định được."
        ),
    )


# ── System prompt ────────────────────────────────────────────────────
SYSTEM_PROMPT = """Bạn là hệ thống AI chuyên phân loại và chuẩn hóa tin cho thuê nhà/phòng trọ
tại thành phố Đà Nẵng, Việt Nam.

Quy tắc quy đổi giá:
- "triệu", "tr" = ×1.000.000  (ví dụ "2tr5" = 2.500.000)
- "k" = ×1.000  (ví dụ "800k" = 800.000)
- "đ" = ×1  (ví dụ "2500000đ" = 2.500.000)
- Giá 1đ, 0đ, 1k, 999đ → spam (giá ảo).
- Giá "thỏa thuận" hoặc "liên hệ" → price_vnd = null.

Quy tắc phân loại:
- Tin CHO THUÊ hợp lệ: có mô tả phòng/nhà, có giá hoặc liên hệ, có khu vực.
- Tin TÌM PHÒNG (người thuê đăng tìm) → is_valid_rental = false.
- Tin pass đồ, bán hàng, quảng cáo dọn nhà → is_valid_rental = false.
- Bài chỉ có ảnh, nội dung rỗng hoặc copy-paste câu like → is_spam = true.

Chuẩn hóa quận Đà Nẵng:
- "HảI châu", "hai chau", "HC" → "Hải Châu"
- "sơn tra", "Son Tra", "ST" → "Sơn Trà"
- "ngu hanh son", "NHS" → "Ngũ Hành Sơn"
- Nếu chỉ ghi tên đường, hãy suy luận quận dựa trên kiến thức địa lý Đà Nẵng.
"""


def _get_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Thiếu biến môi trường GEMINI_API_KEY. "
            "Tạo key tại https://aistudio.google.com/apikey"
        )
    return genai.Client(api_key=api_key)


def analyze_rental(title: str, raw_content: str) -> Dict[str, Any]:
    """
    Gửi nội dung tin đăng tới Gemini 2.5 Flash, nhận về kết quả
    phân loại và chuẩn hóa dưới dạng dict.

    Returns:
        Dict với các key: is_valid_rental, is_spam, price_vnd, district, room_type
    """
    client = _get_client()

    user_prompt = f"Tiêu đề: {title}\nNội dung: {raw_content}"

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=user_prompt,
            config={
                "system_instruction": SYSTEM_PROMPT,
                "response_mime_type": "application/json",
                "response_schema": RentalAnalysis,
                "temperature": 0.1,
            },
        )

        if response.text:
            result = RentalAnalysis.model_validate_json(response.text)
            return result.model_dump()

    except Exception as e:
        logging.warning("Lỗi khi gọi Gemini API cho tin '%s': %s", title[:40], e)

    # Fallback an toàn — không chặn pipeline
    return {
        "is_valid_rental": False,
        "is_spam": False,
        "price_vnd": None,
        "district": None,
        "room_type": None,
    }


def analyze_batch(
    items: list[Dict[str, Any]],
    title_key: str = "title",
    content_key: str = "raw_content",
) -> list[Dict[str, Any]]:
    """
    Phân tích hàng loạt bài đăng. Trả về danh sách dict gốc đã được
    merge thêm các trường từ Gemini (is_valid_rental, is_spam, price_vnd,
    district, room_type).
    """
    results = []
    total = len(items)

    for i, item in enumerate(items, 1):
        title = item.get(title_key, "")
        content = item.get(content_key, "")

        logging.info("[%d/%d] Phân tích: %s", i, total, title[:50])
        analysis = analyze_rental(title, content)

        merged = {**item, **analysis}
        results.append(merged)

    valid = sum(1 for r in results if r.get("is_valid_rental") and not r.get("is_spam"))
    logging.info(
        "Phân tích xong %d bài: %d hợp lệ, %d loại bỏ.",
        total, valid, total - valid,
    )
    return results


if __name__ == "__main__":
    samples = [
        {
            "title": "Cho thuê phòng trọ kiệt Phan Châu Trinh",
            "raw_content": (
                "Phòng 25m2 full nội thất, máy lạnh, nóng lạnh. "
                "Giá 2tr5/tháng cọc 1 tháng. Gần chợ Hàn, quận Hải Châu. "
                "LH 0901234567"
            ),
        },
        {
            "title": "Tìm phòng thuê gấp khu Sơn Trà",
            "raw_content": "Em cần tìm phòng giá 2tr khu Sơn Trà, ai có phòng inbox em",
        },
        {
            "title": "Pass bàn ghế thanh lý giá rẻ",
            "raw_content": "Thanh lý bộ bàn ghế gỗ giá 500k, ai cần inbox nha",
        },
    ]

    print("=== Test ai_filter.py ===\n")
    for s in samples:
        print(f"Input: {s['title']}")
        # result = analyze_rental(s["title"], s["raw_content"])
        # print(f"Output: {result}\n")
    print("(Bỏ comment dòng trên và đặt GEMINI_API_KEY để chạy thật)")
