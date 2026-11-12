"""
ai_filter.py – Bộ lọc & bóc tách dữ liệu tin phòng trọ Đà Nẵng 100% Python thuần.
Sử dụng Regex và Rule-based heuristic: 0 tốn token, tốc độ xử lý tức thì.
"""

import logging
import re
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ai_filter")

# ── 1. Danh sách từ khóa lọc rác & tin tìm trọ ────────────────────────
JUNK_KEYWORDS = [
    "cần tìm",
    "tìm phòng",
    "tìm trọ",
    "pass lại",
    "thanh lý",
    "tuyển dụng",
    "việc làm",
    "vay vốn",
    "sim số",
    "bán đất",
    "sang quán",
    "sang mặt bằng",
    "sang lô",
    "sang shop",
    "sang nhượng",
    "áo quần",
    "quần áo",
]

# Từ khóa xác nhận là tin cho thuê phòng/căn hộ
RENTAL_KEYWORDS = [
    "cho thuê",
    "phòng trọ",
    "căn hộ",
    "studio",
    "chung cư mini",
    "nhà nguyên căn",
    "ở ghép",
    "còn trống",
    "nhà trọ",
    "phòng trống",
    "cho thue",
    "phong tro",
    "can ho",
    "ccmn",
]

# ── 2. Từ điển ánh xạ quận, phường, đường tại Đà Nẵng ─────────────────
DANANG_DISTRICTS = [
    "Hải Châu",
    "Thanh Khê",
    "Sơn Trà",
    "Ngũ Hành Sơn",
    "Liên Chiểu",
    "Cẩm Lệ",
    "Hòa Vang",
]

DISTRICT_MAPPINGS = {
    "Hải Châu": [
        "hải châu", "hai chau", "bạch đằng", "phan châu trinh", "nguyễn văn linh",
        "hùng vương", "trần phú", "lê duẩn", "hải châu 1", "hải châu 2",
        "thạch thang", "thuận phước", "hòa thuận", "nam dương", "bình hiên",
        "bình thuận", "hòa cường bắc", "hòa cường nam", "hòa cường", "đống đa",
        "tiểu la", "hoàng diệu", "núi thành", "nguyễn tri phương", "quang trung",
        "trưng nữ vương", "chợ hàn", "chợ cồn",
    ],
    "Thanh Khê": [
        "thanh khê", "thanh khe", "điện biên phủ", "hà huy tập", "nguyễn tất thành",
        "dũng sĩ thanh khê", "tam thuận", "thanh khê tây", "thanh khê đông",
        "xuân hà", "tân chính", "chính gián", "vĩnh trung", "thạc gián",
        "an khê", "hòa khê", "trần cao vân", "thái thị bôi", "lý thái tổ",
    ],
    "Sơn Trà": [
        "sơn trà", "son tra", "võ nguyên giáp", "phạm văn đồng", "hồ nghinh",
        "an hải bắc", "an hải đông", "an hải tây", "an hải", "phước mỹ",
        "mân thái", "thọ quang", "nại hiên đông", "mỹ khê", "cầu rồng",
        "cầu sông hàn", "hoàng sa", "võ văn kiệt", "ngô quyền",
    ],
    "Ngũ Hành Sơn": [
        "ngũ hành sơn", "ngu hanh son", "ngũ hành", "lê văn hiến", "trần đại nghĩa",
        "khuê mỹ", "mỹ an", "hòa quý", "hòa hải", "châu thị vĩnh tế",
        "phan tứ", "fpt", "vku", "non nước", "bà huyện thanh quan",
    ],
    "Liên Chiểu": [
        "liên chiểu", "lien chieu", "tôn đức thắng", "nguyễn lương bằng",
        "bách khoa", "sư phạm", "hòa khánh bắc", "hòa khánh nam", "hòa khánh",
        "hòa minh", "hòa hiệp bắc", "hòa hiệp nam", "hòa hiệp", "âu cơ",
        "nam ô", "kinh tế",
    ],
    "Cẩm Lệ": [
        "cẩm lệ", "cam le", "cách mạng tháng 8", "cmt8", "ông ích đường",
        "khuê trung", "hòa thọ đông", "hòa thọ tây", "hòa thọ", "hòa xuân",
        "hòa phát", "hòa an", "lê đại hành", "nguyễn hữu thọ",
    ],
    "Hòa Vang": [
        "hòa vang", "hoa vang", "hòa tiến", "hòa châu", "hòa phong",
        "hòa nhơn", "hòa liên", "hòa sơn", "hòa ninh", "hòa bắc", "hòa phú",
        "quốc lộ 14b",
    ],
}


def extract_district(text: str) -> str:
    """Xác định quận tại Đà Nẵng từ tiêu đề, nội dung và địa chỉ."""
    if not text:
        return "Khác"
    t = text.lower()
    for district, keywords in DISTRICT_MAPPINGS.items():
        for kw in keywords:
            # Tìm từ khóa đứng độc lập hoặc trong cụm từ
            if kw in t:
                return district
    return "Khác"


def extract_price_vnd(text: str) -> Optional[int]:
    """Bóc tách giá thuê phòng quy đổi về số nguyên VND bằng Regex."""
    if not text:
        return None
    t = text.lower().strip()

    # 1. Dạng "X củ rưỡi", "X triệu rưỡi", "Xtr rưỡi"
    m = re.search(r'(\d+)\s*(?:triệu|trieu|tr|củ|cu)\s*rưỡi', t)
    if m:
        return int((float(m.group(1)) + 0.5) * 1_000_000)

    # 2. Dạng "XtrY" ví dụ 2tr5, 1tr8, 3tr2, 2tr500
    m = re.search(r'(\d+)\s*tr\s*(\d+)', t)
    if m:
        trieu = int(m.group(1))
        le_str = m.group(2)
        if len(le_str) == 1:
            le = int(le_str) * 100_000
        elif len(le_str) == 2:
            le = int(le_str) * 10_000
        else:
            le = int(le_str[:3].ljust(6, '0'))
        return trieu * 1_000_000 + le

    # 3. Dạng "X.Y triệu", "X,Y triệu", "X triệu", "X.Y tr", "X củ"
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:triệu|trieu|tr|củ|cu)\b', t)
    if m:
        val = float(m.group(1).replace(',', '.'))
        return int(val * 1_000_000)

    # 4. Dạng "2500k", "800k"
    m = re.search(r'(\d+)\s*k\b', t)
    if m:
        return int(m.group(1)) * 1_000

    # 5. Dạng số đầy đủ: "3.500.000", "950,000", "950.000 đ"
    m = re.search(r'(\d{1,3}(?:[.,]\d{3}){1,2})', t)
    if m:
        num_str = re.sub(r'[.,]', '', m.group(1))
        return int(num_str)

    # 6. Số liền 6-8 chữ số
    m = re.search(r'\b(\d{6,8})\b', t)
    if m:
        return int(m.group(1))

    return None


def extract_room_type(text: str) -> str:
    """Phân loại loại phòng theo từ khóa."""
    t = (text or "").lower()
    if any(k in t for k in ["studio", "căn hộ", "chung cư", "ccmn", "duplex", "penthouse", "condo", "apartment"]):
        return "Chung cư mini / Căn hộ"
    if any(k in t for k in ["nguyên căn", "nhà riêng", "nhà mặt tiền", "nhà phố", "nhà kiệt"]):
        return "Nhà nguyên căn"
    if any(k in t for k in ["ở ghép", "tìm bạn ở ghép", "tìm người ở ghép", "share phòng", "homestay"]):
        return "Ở ghép"
    return "Phòng trọ"


# Regex nhận diện số điện thoại di động Việt Nam (10 số, đầu 03, 05, 07, 08, 09)
PHONE_RE = re.compile(
    r'(?:\+?84|0)(?:3[2-9]|5[25689]|7[06-9]|8[1-9]|9\d)[\s.-]?(?:\d[\s.-]?){7}\b'
)


def extract_phone(text: str) -> Optional[str]:
    """
    Bóc tách số điện thoại di động Việt Nam từ văn bản.
    Chuẩn hóa về dạng 10 chữ số chuẩn: 0XXXXXXXXX.
    """
    if not text:
        return None

    matches = PHONE_RE.findall(text)
    for m in matches:
        # Làm sạch các ký tự phân cách
        cleaned = re.sub(r'[\s.\-+()]', '', m)
        if cleaned.startswith("84") and len(cleaned) == 11:
            cleaned = "0" + cleaned[2:]
        if len(cleaned) == 10 and cleaned.startswith(("03", "05", "07", "08", "09")):
            return cleaned

    # Fallback quét chuỗi số 10 số liền nhau
    fallback = re.findall(r'\b(0[35789]\d{8})\b', text)
    if fallback:
        return fallback[0]

    return None


AREA_RE = re.compile(
    r'(\d+(?:[.,]\d+)?)\s*(?:m2|m²|mét vuông|met vuong)\b',
    re.IGNORECASE,
)


def extract_area_m2(text: str) -> Optional[float]:
    """
    Bóc tách diện tích phòng (m2) từ văn bản bằng Regex.
    Giới hạn diện tích thực tế từ 8 m² đến 200 m².
    """
    if not text:
        return None

    matches = AREA_RE.findall(text)
    for m in matches:
        try:
            val = float(m.replace(',', '.'))
            if 8.0 <= val <= 200.0:
                return round(val, 1)
        except ValueError:
            continue

    return None


def filter_and_extract(
    title: str,
    raw_content: str,
    existing_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Hàm phân tích, chuẩn hóa và lọc tin rác 100% bằng Python & Regex.
    Không tốn token API, trả kết quả tức thì.

    Returns:
        {
            "is_valid_rental": bool,
            "is_spam": bool,
            "price_vnd": Optional[int],
            "district": str,
            "room_type": str,
            "phone": Optional[str],
            "area_m2": Optional[float],
            "image_url": Optional[str],
        }
    """
    existing_data = existing_data or {}
    full_text = f"{title} {raw_content}".lower()

    # 1. Kiểm tra từ khóa rác / tìm trọ
    for junk in JUNK_KEYWORDS:
        if junk in full_text:
            return {
                "is_valid_rental": False,
                "is_spam": False,
                "price_vnd": None,
                "district": "Khác",
                "room_type": "Phòng trọ",
                "phone": None,
                "area_m2": None,
                "image_url": None,
            }

    # 2. Kiểm tra có phải tin cho thuê phòng không
    source = existing_data.get("source", "").lower()
    is_from_rental_site = source in ["phongtro123", "chotot"]
    has_rental_keyword = any(k in full_text for k in RENTAL_KEYWORDS)

    if not is_from_rental_site and not has_rental_keyword:
        return {
            "is_valid_rental": False,
            "is_spam": False,
            "price_vnd": None,
            "district": "Khác",
            "room_type": "Phòng trọ",
            "phone": None,
            "area_m2": None,
            "image_url": None,
        }

    # 3. Lấy hoặc bóc tách giá tiền
    price_vnd = existing_data.get("price_vnd")
    if price_vnd is None:
        price_vnd = extract_price_vnd(full_text)

    # 4. Kiểm tra giá ảo / spam
    is_spam = False
    if price_vnd is not None:
        # Giá < 500,000 VND (1k, 0đ, 1000đ) hoặc > 50 triệu (bán đất/nhà) -> coi là spam
        if price_vnd < 500_000 or price_vnd > 50_000_000:
            is_spam = True

    # 5. Lấy hoặc bóc tách quận/huyện
    district = existing_data.get("district")
    if not district or district == "Khác":
        district = extract_district(f"{title} {raw_content}")

    # 6. Phân loại phòng
    room_type = existing_data.get("room_type") or extract_room_type(full_text)

    # 7. Bóc tách số điện thoại liên hệ
    phone = existing_data.get("phone")
    if not phone:
        phone = extract_phone(f"{title} {raw_content}")

    # 8. Bóc tách diện tích phòng (m2)
    area_m2 = existing_data.get("area_m2")
    if area_m2 is None:
        area_m2 = extract_area_m2(f"{title} {raw_content}")

    # 9. Ảnh đại diện bài viết
    image_url = existing_data.get("image_url")

    return {
        "is_valid_rental": True,
        "is_spam": is_spam,
        "price_vnd": price_vnd,
        "district": district or "Khác",
        "room_type": room_type,
        "phone": phone,
        "area_m2": area_m2,
        "image_url": image_url,
    }


# Alias giữ nguyên để tương thích ngược với các hàm gọi cũ
analyze_rental = filter_and_extract


def analyze_batch(
    items: List[Dict[str, Any]],
    title_key: str = "title",
    content_key: str = "raw_content",
) -> List[Dict[str, Any]]:
    """Phân tích hàng loạt tin bằng regex & rule-based."""
    results = []
    for item in items:
        title = item.get(title_key, "")
        content = item.get(content_key, "")
        analysis = filter_and_extract(title, content, existing_data=item)
        results.append({**item, **analysis})
    return results


if __name__ == "__main__":
    test_cases = [
        ("Cho thuê phòng trọ kiệt Phan Châu Trinh", "Phòng 25m2 full nội thất, giá 2tr5/tháng quận Hải Châu"),
        ("Studio view biển Mỹ Khê", "Căn hộ studio 3.9 triệu/tháng Ngũ Hành Sơn đầy đủ tiện nghi"),
        ("Tìm phòng thuê gấp", "Em cần tìm phòng giá 2tr khu vực Thanh Khê"),
        ("Pass bàn ghế gỗ", "Thanh lý bàn ghế giá 500k ai mua inbox"),
        ("Phòng trọ giá rẻ", "Phòng trọ giá 1k liên hệ gấp"),
        ("Phòng trọ Hoà Khánh", "Gần Bách Khoa, giá 1tr2, vệ sinh khép kín"),
    ]
    print("=== TEST AI_FILTER (REGEX 0 TOKEN) ===")
    for title, content in test_cases:
        res = filter_and_extract(title, content)
        print(f"'{title}': valid={res['is_valid_rental']}, spam={res['is_spam']}, price={res['price_vnd']}, district={res['district']}, type={res['room_type']}")
