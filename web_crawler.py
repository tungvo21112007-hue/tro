"""
web_crawler.py – Cào danh sách tin cho thuê phòng trọ khu vực Đà Nẵng
từ phongtro123.com sử dụng crawlee (BeautifulSoupCrawler).
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List
from urllib.parse import urljoin

from crawlee.crawlers import BeautifulSoupCrawler, BeautifulSoupCrawlingContext

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

BASE_URL = "https://phongtro123.com"
START_URL = f"{BASE_URL}/tinh/da-nang"

# Biến tích lũy kết quả xuyên suốt phiên crawl
_collected_items: List[Dict[str, Any]] = []


def _parse_relative_time(raw_text: str) -> str:
    """
    Chuyển chuỗi thời gian tương đối trên trang (ví dụ "Hôm nay", "2 ngày trước",
    "1 tuần trước") thành ISO 8601 datetime. Fallback = thời điểm hiện tại.
    """
    now = datetime.now()
    text = raw_text.strip().lower()

    if "hôm nay" in text:
        return now.isoformat()
    if "hôm qua" in text:
        return (now - timedelta(days=1)).isoformat()

    # "X phút trước", "X giờ trước", "X ngày trước", "X tuần trước", "X tháng trước"
    match = re.search(r"(\d+)\s*(phút|giờ|ngày|tuần|tháng)", text)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        delta_map = {
            "phút": timedelta(minutes=amount),
            "giờ": timedelta(hours=amount),
            "ngày": timedelta(days=amount),
            "tuần": timedelta(weeks=amount),
            "tháng": timedelta(days=amount * 30),
        }
        delta = delta_map.get(unit, timedelta())
        return (now - delta).isoformat()

    # Thử parse trực tiếp các dạng dd/mm/yyyy
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).isoformat()
        except ValueError:
            continue

    return now.isoformat()


def _build_raw_content(price: str, acreage: str, location: str, summary: str) -> str:
    """Ghép nối các trường thành chuỗi raw_content mô tả bài đăng."""
    parts = [p.strip() for p in [price, acreage, location, summary] if p and p.strip()]
    return " | ".join(parts) if parts else ""


async def _run_crawler(
    start_url: str = START_URL,
    max_requests: int = 30,
) -> None:
    """Khởi chạy BeautifulSoupCrawler, lưu kết quả vào _collected_items."""
    global _collected_items
    _collected_items = []

    crawler = BeautifulSoupCrawler(
        max_requests_per_crawl=max_requests,
    )

    @crawler.router.default_handler
    async def request_handler(context: BeautifulSoupCrawlingContext) -> None:
        soup = context.soup
        context.log.info(f"Đang xử lý: {context.request.url}")

        # --- Trích xuất danh sách bài đăng ---
        # phongtro123 dùng .post-item hoặc .js-post-item làm container mỗi tin.
        # Fallback qua nhiều selector phòng trường hợp trang đổi class.
        post_items = (
            soup.select("div.post-item")
            or soup.select("li.post-item")
            or soup.select("section.post-listing div[class*='post']")
            or soup.select("ul.post-listing > li")
        )

        if not post_items:
            context.log.warning(
                f"Không tìm thấy bài đăng nào tại {context.request.url}. "
                "Có thể CSS selector đã thay đổi — kiểm tra lại bằng Inspect (F12)."
            )

        for item in post_items:
            # Tiêu đề + link chi tiết
            title_el = (
                item.select_one("h3.post-title a")
                or item.select_one(".post-title a")
                or item.select_one("h3 a")
            )
            title = title_el.get_text(strip=True) if title_el else ""
            relative_url = title_el.get("href", "") if title_el else ""
            detail_url = urljoin(BASE_URL, relative_url) if relative_url else ""

            # Giá, diện tích, khu vực
            price_el = item.select_one(".post-price") or item.select_one("span[class*='price']")
            price_text = price_el.get_text(strip=True) if price_el else ""

            acreage_el = item.select_one(".post-acreage") or item.select_one("span[class*='acreage']")
            acreage_text = acreage_el.get_text(strip=True) if acreage_el else ""

            location_el = item.select_one(".post-location") or item.select_one("span[class*='location']")
            location_text = location_el.get_text(strip=True) if location_el else ""

            # Mô tả ngắn
            summary_el = item.select_one(".post-summary") or item.select_one("p[class*='summary']")
            summary_text = summary_el.get_text(strip=True) if summary_el else ""

            # Thời gian đăng
            time_el = item.select_one(".post-time") or item.select_one("span[class*='time']")
            raw_time = time_el.get_text(strip=True) if time_el else ""

            # Bỏ qua mục không có tiêu đề hoặc URL
            if not title or not detail_url:
                continue

            raw_content = _build_raw_content(price_text, acreage_text, location_text, summary_text)

            _collected_items.append(
                {
                    "title": title[:50],
                    "raw_content": raw_content or title,
                    "url": detail_url,
                    "source": "Phongtro123",
                    "posted_time": _parse_relative_time(raw_time) if raw_time else datetime.now().isoformat(),
                }
            )

        # --- Phân trang: enqueue trang tiếp theo ---
        next_link = (
            soup.select_one("a.page-link[rel='next']")
            or soup.select_one("li.page-item.active + li a")
            or soup.select_one("a[title='Trang sau']")
        )
        if next_link and next_link.get("href"):
            next_url = urljoin(BASE_URL, next_link["href"])
            context.log.info(f"Tìm thấy trang tiếp theo: {next_url}")
            await context.add_requests([next_url])

    await crawler.run([start_url])


def crawl_phongtro123(
    start_url: str = START_URL,
    max_requests: int = 30,
) -> List[Dict[str, Any]]:
    """
    Hàm đồng bộ cào tin cho thuê từ phongtro123.com khu vực Đà Nẵng.

    Returns:
        Danh sách dict cùng cấu trúc với fb_crawler.py:
        {title, raw_content, url, source, posted_time}
    """
    asyncio.run(_run_crawler(start_url=start_url, max_requests=max_requests))

    logging.info("Phongtro123: Thu thập được %d bài đăng hợp lệ.", len(_collected_items))
    return list(_collected_items)


if __name__ == "__main__":
    results = crawl_phongtro123()
    for i, post in enumerate(results[:5], 1):
        print(f"\n--- Bài #{i} ---")
        print(f"  Title:  {post['title']}")
        print(f"  URL:    {post['url']}")
        print(f"  Source: {post['source']}")
        print(f"  Time:   {post['posted_time']}")
        print(f"  Content: {post['raw_content'][:120]}")
    print(f"\nTổng cộng: {len(results)} bài đăng.")
