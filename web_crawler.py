"""
web_crawler.py – Thu thập và bóc tách dữ liệu có cấu trúc từ:
  * Phongtro123 (HTML bằng requests + BeautifulSoup, trích xuất giá & quận trực tiếp)
  * Chợ Tốt / nhatot.com (API JSON gateway.chotot.com, bóc tách giá số nguyên & quận)
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("web_crawler")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9",
}
TIMEOUT = 20

# Danh sách quận chuẩn tại Đà Nẵng
DANANG_DISTRICTS = [
    "Hải Châu",
    "Thanh Khê",
    "Sơn Trà",
    "Ngũ Hành Sơn",
    "Liên Chiểu",
    "Cẩm Lệ",
    "Hòa Vang",
]

DISTRICT_MAP = {
    "hải châu": "Hải Châu",
    "hai chau": "Hải Châu",
    "thanh khê": "Thanh Khê",
    "thanh khe": "Thanh Khê",
    "sơn trà": "Sơn Trà",
    "son tra": "Sơn Trà",
    "ngũ hành sơn": "Ngũ Hành Sơn",
    "ngu hanh son": "Ngũ Hành Sơn",
    "liên chiểu": "Liên Chiểu",
    "lien chieu": "Liên Chiểu",
    "cẩm lệ": "Cẩm Lệ",
    "cam le": "Cẩm Lệ",
    "hòa vang": "Hòa Vang",
    "hoa vang": "Hòa Vang",
}


def normalize_district(raw_location: str) -> Optional[str]:
    """Chuẩn hóa chuỗi địa chỉ về một trong 7 quận Đà Nẵng."""
    if not raw_location:
        return None
    loc = raw_location.lower()
    for key, district in DISTRICT_MAP.items():
        if key in loc:
            return district
    return None


def parse_price_text(text: str) -> Optional[int]:
    """Bóc tách chuỗi giá tiếng Việt sang số nguyên VND."""
    if not text:
        return None
    t = text.lower().strip()

    # Dạng "2 củ rưỡi", "2 triệu rưỡi", "2tr rưỡi"
    m = re.search(r'(\d+)\s*(?:triệu|trieu|tr|củ|cu)\s*rưỡi', t)
    if m:
        return int((float(m.group(1)) + 0.5) * 1_000_000)

    # Dạng "XtrY" ví dụ 2tr5, 1tr8, 3tr2, 2tr500
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

    # Dạng "X.Y triệu", "X,Y triệu", "X triệu", "X.Y tr", "X củ"
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:triệu|trieu|tr|củ|cu)\b', t)
    if m:
        val = float(m.group(1).replace(',', '.'))
        return int(val * 1_000_000)

    # Dạng "2500k", "800k"
    m = re.search(r'(\d+)\s*k\b', t)
    if m:
        return int(m.group(1)) * 1_000

    # Dạng số đầy đủ: "3.500.000", "950,000", "950.000 đ"
    m = re.search(r'(\d{1,3}(?:[.,]\d{3}){1,2})', t)
    if m:
        num_str = re.sub(r'[.,]', '', m.group(1))
        return int(num_str)

    # Số liền 6-8 chữ số
    m = re.search(r'\b(\d{6,8})\b', t)
    if m:
        return int(m.group(1))

    return None


def detect_room_type(text: str) -> str:
    """Phân loại loại phòng dựa trên từ khóa trong tiêu đề/nội dung."""
    t = (text or "").lower()
    if any(k in t for k in ["studio", "căn hộ", "chung cư", "ccmn", "duplex", "penthouse", "condo", "apartment"]):
        return "Chung cư mini / Căn hộ"
    if any(k in t for k in ["nguyên căn", "nhà riêng", "nhà mặt tiền", "nhà phố", "nhà kiệt"]):
        return "Nhà nguyên căn"
    if any(k in t for k in ["ở ghép", "tìm bạn ở ghép", "tìm người ở ghép", "share phòng", "homestay"]):
        return "Ở ghép"
    return "Phòng trọ"


# ── Phongtro123 ──────────────────────────────────────────────────────
PT_BASE = "https://phongtro123.com"
PT_LIST_URL = f"{PT_BASE}/tinh-thanh/da-nang"
PT_TIME_RE = re.compile(r"(\d{1,2}:\d{2})\s+(\d{1,2}/\d{1,2}/\d{4})")


def _pt_time(item) -> str:
    el = item.select_one("time")
    m = PT_TIME_RE.search((el.get("title") or "") if el else "")
    if m:
        try:
            return datetime.strptime(f"{m.group(2)} {m.group(1)}", "%d/%m/%Y %H:%M").isoformat()
        except ValueError:
            pass
    return datetime.now().isoformat()


def crawl_phongtro123(pages: int = 2) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    seen = set()

    for page in range(1, pages + 1):
        try:
            resp = requests.get(
                PT_LIST_URL,
                params={"page": page} if page > 1 else None,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            log.error("Phongtro123 trang %d lỗi: %s", page, e)
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        for item in soup.select("ul.post__listing > li"):
            link = item.select_one("h3 a[href]")
            if not link:
                continue
            url = PT_BASE + link["href"] if link["href"].startswith("/") else link["href"]
            if url in seen:
                continue
            seen.add(url)

            title = link.get_text(" ", strip=True)
            price_el = item.select_one(".text-green")
            price_str = price_el.get_text(strip=True) if price_el else ""
            price_vnd = parse_price_text(price_str)

            geo = item.select_one(".geo-alt")
            location_str = geo.parent.get_text(" ", strip=True) if geo else ""
            district = normalize_district(location_str) or normalize_district(title)

            summary = item.select_one("p.text-secondary")
            summary_str = summary.get_text(" ", strip=True) if summary else ""

            parts = [title, price_str, location_str, summary_str]
            raw_content = " | ".join(p for p in parts if p)

            room_type = detect_room_type(f"{title} {raw_content}")

            results.append({
                "title": title[:50],
                "raw_content": raw_content,
                "price_vnd": price_vnd,
                "district": district,
                "room_type": room_type,
                "url": url,
                "source": "Phongtro123",
                "posted_time": _pt_time(item),
            })

    log.info("Phongtro123: bóc tách thành công %d tin.", len(results))
    return results


# ── Chợ Tốt (nhatot.com) ─────────────────────────────────────────────
CHOTOT_API = "https://gateway.chotot.com/v1/public/ad-listing"
CHOTOT_PARAMS = {
    "cg": 1050,          # danh mục: Phòng trọ
    "region_v2": 3017,   # Đà Nẵng
    "st": "u",           # u = cho thuê
    "limit": 20,
}


def crawl_chotot(pages: int = 2) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    for page in range(pages):
        try:
            resp = requests.get(
                CHOTOT_API,
                params={**CHOTOT_PARAMS, "o": page * CHOTOT_PARAMS["limit"]},
                headers=HEADERS,
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            ads = resp.json().get("ads", [])
        except (requests.RequestException, ValueError) as e:
            log.error("Chợ Tốt offset %d lỗi: %s", page, e)
            break
        if not ads:
            break

        for ad in ads:
            list_id = ad.get("list_id")
            if not list_id:
                continue

            subject = (ad.get("subject") or "").strip()
            body = (ad.get("body") or "").strip()

            # Lấy trực tiếp giá nguyên từ API Chợ Tốt
            price_val = ad.get("price")
            price_vnd = int(price_val) if isinstance(price_val, (int, float)) and price_val > 0 else None
            price_display = ad.get("price_string") or (f"{price_vnd:,}đ" if price_vnd else "")

            # Chuẩn hóa tên quận từ area_name ("Quận Thanh Khê" -> "Thanh Khê")
            raw_area = ad.get("area_name") or ""
            raw_ward = ad.get("ward_name") or ""
            district = normalize_district(raw_area) or normalize_district(raw_ward) or normalize_district(subject)

            size_str = f"{ad['size']} m²" if ad.get("size") else ""
            location_full = ", ".join(x for x in (raw_ward, raw_area, ad.get("region_name")) if x)
            parts = [subject, price_display, size_str, location_full, body]
            raw_content = " | ".join(p for p in parts if p)

            room_type = detect_room_type(f"{subject} {body}")

            ts = ad.get("list_time")  # epoch ms
            posted_time = (
                datetime.fromtimestamp(ts / 1000).isoformat() if ts else datetime.now().isoformat()
            )

            results.append({
                "title": subject[:50],
                "raw_content": raw_content,
                "price_vnd": price_vnd,
                "district": district,
                "room_type": room_type,
                "url": f"https://www.nhatot.com/{list_id}.htm",
                "source": "Chotot",
                "posted_time": posted_time,
            })

    log.info("Chợ Tốt: bóc tách thành công %d tin.", len(results))
    return results


if __name__ == "__main__":
    for name, fn in (("Phongtro123", crawl_phongtro123), ("Chotot", crawl_chotot)):
        data = fn(pages=1)
        print(f"\n== {name}: {len(data)} tin ==")
        for p in data[:2]:
            print(f"[{p['posted_time']}] {p['district']} | {p['room_type']} | {p['price_vnd']:,}đ" if p['price_vnd'] else f"[{p['posted_time']}] {p['district']} | {p['room_type']} | Thỏa thuận")
            print("   Title:", p["title"])
            print("   URL:  ", p["url"])
