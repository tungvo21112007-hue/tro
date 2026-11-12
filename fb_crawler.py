"""
fb_crawler.py – Cào bài viết Facebook Group cho thuê trọ Đà Nẵng bằng Playwright (không dùng Apify).

Lưu ý: Facebook thường chặn khách chưa đăng nhập. Để ổn định, đăng nhập 1 lần để lưu session:
    python fb_crawler.py --login
Session lưu ở thư mục fb_profile/ (đã nằm trong .gitignore).
"""

import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

PROFILE_DIR = Path(__file__).resolve().parent / "fb_profile"

DEFAULT_GROUP_URLS = [
    "https://www.facebook.com/groups/thuephongtrodanang",
    "https://www.facebook.com/groups/phongtrodanang",
    "https://www.facebook.com/groups/nhatrodanang",
]

DEFAULT_RESULTS_LIMIT = 20
MAX_SCROLLS = 8
POST_LINK_RE = re.compile(r"/(posts|permalink)/\d+|story_fbid=|/groups/[^/]+/posts/")


def _clean_url(href: str) -> str:
    full = urljoin("https://www.facebook.com", href)
    return full.split("?")[0] if "story_fbid" not in full else full


def _extract_posts(page, limit: int) -> List[Dict[str, Any]]:
    posts: Dict[str, Dict[str, Any]] = {}

    for _ in range(MAX_SCROLLS):
        for article in page.locator("div[role='article']").all():
            try:
                link = next(
                    (
                        a.get_attribute("href")
                        for a in article.locator("a[href]").all()
                        if POST_LINK_RE.search(a.get_attribute("href") or "")
                    ),
                    None,
                )
                if not link:
                    continue
                url = _clean_url(link)
                if url in posts:
                    continue

                # Bấm "Xem thêm" để lấy đủ nội dung nếu có
                more = article.get_by_role("button", name=re.compile(r"Xem thêm|See more"))
                if more.count():
                    more.first.click(timeout=1000)

                text = article.inner_text(timeout=2000).strip()
                if not text:
                    continue

                posts[url] = {
                    "title": text[:50].replace("\n", " ").strip(),
                    "raw_content": text,
                    "url": url,
                    "source": "Facebook",
                    # shortcut: Facebook giấu timestamp tuyệt đối, dùng giờ cào; nâng cấp bằng parse aria-label khi cần
                    "posted_time": datetime.now().isoformat(),
                }
            except Exception:
                continue  # 1 thẻ lỗi không làm hỏng cả group

        if len(posts) >= limit:
            break
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(2000)

    return list(posts.values())[:limit]


def crawl_fb_groups(
    group_urls: Optional[List[str]] = None,
    results_limit: int = DEFAULT_RESULTS_LIMIT,
    headless: bool = True,
) -> List[Dict[str, Any]]:
    """Mở từng group công khai, cuộn trang, trả list dict {title, raw_content, url, source, posted_time}."""
    urls = group_urls or [
        u.strip() for u in os.getenv("FB_GROUP_URLS", "").split(",") if u.strip()
    ] or DEFAULT_GROUP_URLS
    results: List[Dict[str, Any]] = []

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=headless, locale="vi-VN"
        )
        page = ctx.new_page()
        for url in urls:
            try:
                logging.info("Mở group: %s", url)
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)
                if "login" in page.url or page.locator("input[name='pass']").count():
                    logging.warning("Facebook yêu cầu đăng nhập, bỏ qua %s (chạy --login).", url)
                    continue
                items = _extract_posts(page, results_limit)
                logging.info("  → %d bài", len(items))
                results.extend(items)
            except Exception as e:
                logging.error("Lỗi khi cào %s: %s", url, e)
        ctx.close()

    return results


def login_interactive() -> None:
    """Mở trình duyệt có giao diện để user đăng nhập tay, session được lưu vào fb_profile/."""
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(PROFILE_DIR), headless=False)
        page = ctx.new_page()
        page.goto("https://www.facebook.com/login")
        input("Đăng nhập xong trong cửa sổ trình duyệt rồi nhấn Enter tại đây...")
        ctx.close()


if __name__ == "__main__":
    if "--login" in sys.argv:
        login_interactive()
    else:
        posts = crawl_fb_groups(headless="--show" not in sys.argv)
        for post in posts[:3]:
            print(post["url"], "|", post["title"])
        print(f"Tổng cộng: {len(posts)} bài viết.")
