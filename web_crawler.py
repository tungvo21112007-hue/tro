"""
web_crawler.py – Thu thập tin cho thuê phòng trọ Đà Nẵng từ:
  * Phongtro123 (requests + BeautifulSoup, đọc HTML)
  * Chợ Tốt / nhatot.com (API JSON công khai gateway.chotot.com)
Đầu ra mỗi nguồn: list[dict] {title, raw_content, url, source, posted_time}
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, List

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

# ── Phongtro123 ──────────────────────────────────────────────────────
PT_BASE = "https://phongtro123.com"
PT_LIST_URL = f"{PT_BASE}/tinh-thanh/da-nang"  # URL có dấu cũ trả 410 Gone
PT_TIME_RE = re.compile(r"(\d{1,2}:\d{2})\s+(\d{1,2}/\d{1,2}/\d{4})")


def _pt_time(item) -> str:
    """Đọc thời gian tuyệt đối trong <time title="Thứ 5, 16:45 12/11/2026">."""
    el = item.select_one("time")
    m = PT_TIME_RE.search((el.get("title") or "") if el else "")
    if m:
        try:
            return datetime.strptime(f"{m.group(2)} {m.group(1)}", "%d/%m/%Y %H:%M").isoformat()
        except ValueError:
            pass
    return datetime.now().isoformat()  # shortcut: không đọc được giờ thì dùng giờ cào


def crawl_phongtro123(pages: int = 2) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    seen = set()

    for page in range(1, pages + 1):
        try:
            resp = requests.get(
                PT_LIST_URL, params={"page": page} if page > 1 else None,
                headers=HEADERS, timeout=TIMEOUT,
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
            price = item.select_one(".text-green")
            geo = item.select_one(".geo-alt")
            location = geo.parent.get_text(" ", strip=True) if geo else ""
            summary = item.select_one("p.text-secondary")
            parts = [
                title,
                price.get_text(strip=True) if price else "",
                location,
                summary.get_text(" ", strip=True) if summary else "",
            ]
            results.append({
                "title": title[:50],
                "raw_content": " | ".join(p for p in parts if p),
                "url": url,
                "source": "Phongtro123",
                "posted_time": _pt_time(item),
            })

    log.info("Phongtro123: %d tin.", len(results))
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
                CHOTOT_API, params={**CHOTOT_PARAMS, "o": page * CHOTOT_PARAMS["limit"]},
                headers=HEADERS, timeout=TIMEOUT,
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
            price = ad.get("price_string") or (f"{ad['price']:,}đ" if ad.get("price") else "")
            size = f"{ad['size']} m²" if ad.get("size") else ""
            location = ", ".join(x for x in (ad.get("ward_name"), ad.get("area_name"), ad.get("region_name")) if x)
            parts = [subject, price, size, location, (ad.get("body") or "").strip()]

            ts = ad.get("list_time")  # epoch mili-giây
            results.append({
                "title": subject[:50],
                "raw_content": " | ".join(p for p in parts if p),
                "url": f"https://www.nhatot.com/{list_id}.htm",
                "source": "Chotot",
                "posted_time": (
                    datetime.fromtimestamp(ts / 1000).isoformat() if ts else datetime.now().isoformat()
                ),
            })

    log.info("Chợ Tốt: %d tin.", len(results))
    return results


if __name__ == "__main__":
    for name, fn in (("Phongtro123", crawl_phongtro123), ("Chotot", crawl_chotot)):
        data = fn()
        print(f"\n== {name}: {len(data)} tin ==")
        for p in data[:2]:
            print(p["posted_time"], "|", p["title"], "|", p["url"])
            print("   ", p["raw_content"][:140])
