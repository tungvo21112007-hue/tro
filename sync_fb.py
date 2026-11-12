#!/usr/bin/env python3
"""
sync_fb.py – Script đồng bộ nhanh bài viết Facebook từ máy local (IP Việt Nam) lên GitHub.
Quy trình:
1. Kiểm tra trạng thái cookie/session Facebook; tự động mở Chromium đăng nhập nếu hết hạn.
2. Cào bài viết từ 8 Facebook Groups phòng trọ Đà Nẵng bằng Playwright.
3. Bóc tách & phân loại 100% bằng Python thuần / Regex (0 tốn token AI), lưu vào rentals.db.
4. Tự động git pull --rebase, git commit và git push rentals.db lên nhánh main để Streamlit Cloud cập nhật.
"""

import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Thiết lập logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sync_fb")

PROJECT_DIR = Path(__file__).resolve().parent
DB_PATH = PROJECT_DIR / "rentals.db"

# Đảm bảo import được các module trong dự án
sys.path.insert(0, str(PROJECT_DIR))

from ai_filter import filter_and_extract
from database import init_db, insert_rental, url_exists
from fb_crawler import (
    COOKIE_FILE,
    DEFAULT_FB_GROUPS,
    PROFILE_DIR,
    crawl_fb_groups,
    get_persisted_cookies,
    login_interactive,
)


def check_fb_session() -> bool:
    """
    Kiểm tra nhanh xem cookie Facebook hiện tại còn hiệu lực hay không.
    Trả về True nếu session hợp lệ, False nếu bị chuyển hướng về trang /login/.
    """
    cookies = get_persisted_cookies()
    if not cookies and not PROFILE_DIR.exists():
        log.warning("Chưa tìm thấy cookie hoặc profile Facebook cục bộ.")
        return False

    log.info("Đang kiểm tra tính hợp lệ của session Facebook...")
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            ctx = browser.new_context(
                locale="vi-VN",
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            )
            if cookies:
                ctx.add_cookies(cookies)

            page = ctx.new_page()
            # Thử truy cập Facebook home hoặc group đầu tiên
            test_url = DEFAULT_FB_GROUPS[0]
            page.goto(test_url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(2000)

            current_url = page.url.lower()
            browser.close()

            if "login" in current_url or "checkpoint" in current_url:
                log.warning("Session Facebook đã hết hạn (chuyển hướng về: %s)", current_url)
                return False

            log.info("✅ Session Facebook còn hiệu lực tốt!")
            return True
    except Exception as e:
        log.warning("Lỗi trong quá trình kiểm tra session: %s. Tiếp tục thử cào trực tiếp.", e)
        return True


def ensure_valid_session() -> None:
    """Đảm bảo có session hợp lệ trước khi cào; mở giao diện đăng nhập nếu cần."""
    if not check_fb_session():
        log.info("Mở trình duyệt Chromium để người dùng đăng nhập lại Facebook...")
        login_interactive()


def sync_facebook_rentals(results_limit: int = 25) -> int:
    """
    Cào các nhóm Facebook, lọc tin spam/tìm phòng, và lưu tin hợp lệ vào database.
    Trả về số bài viết mới được thêm vào database.
    """
    init_db(DB_PATH)

    # Đảm bảo cờ ép buộc được bật khi chạy script đồng bộ local
    os.environ["FORCE_FB_SCRAPE"] = "true"

    log.info("Bắt đầu cào dữ liệu từ %d Facebook Groups Đà Nẵng...", len(DEFAULT_FB_GROUPS))
    raw_items = crawl_fb_groups(results_limit=results_limit, headless=True)
    log.info("Tổng số bài viết thô thu thập từ Facebook: %d bài.", len(raw_items))

    if not raw_items:
        log.warning("Không thu thập được bài viết nào từ Facebook.")
        return 0

    new_saved = 0
    skipped_existing = 0
    skipped_invalid = 0
    skipped_spam = 0

    for i, item in enumerate(raw_items, 1):
        url = item.get("url")
        if not url:
            continue

        if url_exists(url, DB_PATH):
            skipped_existing += 1
            continue

        title = item.get("title", "")
        raw_content = item.get("raw_content", "")

        try:
            analysis = filter_and_extract(title, raw_content, existing_data=item)
        except Exception as e:
            log.warning("Lỗi phân tích bài viết '%s': %s", title[:40], e)
            continue

        if not analysis.get("is_valid_rental"):
            skipped_invalid += 1
            continue

        if analysis.get("is_spam"):
            skipped_spam += 1
            continue

        record = {
            "title": title,
            "raw_content": raw_content,
            "price_vnd": analysis.get("price_vnd"),
            "district": analysis.get("district"),
            "room_type": analysis.get("room_type"),
            "url": url,
            "source": item.get("source", "Facebook"),
            "posted_time": item.get("posted_time") or datetime.now().isoformat(),
            "created_at": datetime.now().isoformat(),
            "image_url": analysis.get("image_url") or item.get("image_url"),
            "phone": analysis.get("phone") or item.get("phone"),
            "area_m2": (
                analysis.get("area_m2")
                if analysis.get("area_m2") is not None
                else item.get("area_m2")
            ),
        }

        if insert_rental(record, DB_PATH):
            new_saved += 1
            price_str = f"{record['price_vnd']:,}đ" if record.get("price_vnd") else "Thỏa thuận"
            log.info(
                "  + Đã lưu: [%s] %s | %s | %s",
                record["district"],
                price_str,
                record["room_type"],
                title[:40],
            )

    log.info(
        "Kết quả lọc & lưu Facebook: %d bài mới, %d bài đã tồn tại, %d bài không phải tin cho thuê, %d tin spam.",
        new_saved,
        skipped_existing,
        skipped_invalid,
        skipped_spam,
    )
    return new_saved


def push_to_github() -> None:
    """Tự động kéo rebase mới nhất, commit rentals.db và push lên GitHub origin main."""
    try:
        log.info("Đang kiểm tra trạng thái Git và kéo cập nhật từ origin/main...")
        subprocess.run(["git", "pull", "--rebase", "origin", "main"], check=True, cwd=PROJECT_DIR)

        status = subprocess.run(
            ["git", "status", "--porcelain", "rentals.db"],
            capture_output=True,
            text=True,
            check=True,
            cwd=PROJECT_DIR,
        )

        if status.stdout.strip():
            log.info("Phát hiện thay đổi mới trong rentals.db. Đang commit và push...")
            subprocess.run(["git", "add", "rentals.db"], check=True, cwd=PROJECT_DIR)
            subprocess.run(
                [
                    "git",
                    "commit",
                    "-m",
                    "chore(data): sync Facebook rentals from local IP",
                ],
                check=True,
                cwd=PROJECT_DIR,
            )
            subprocess.run(["git", "push", "origin", "main"], check=True, cwd=PROJECT_DIR)
            log.info("🚀 Đã đẩy rentals.db mới nhất lên GitHub thành công!")
        else:
            log.info("Không có thay đổi mới trong rentals.db, không cần push.")
    except subprocess.CalledProcessError as e:
        log.error("Lỗi khi thực thi lệnh Git: %s", e)
    except Exception as e:
        log.error("Lỗi bất ngờ trong quá trình Git sync: %s", e)


def main():
    print("=" * 65)
    print("  ĐỒNG BỘ TIN PHÒNG TRỌ FACEBOOK (LOCAL IP -> GITHUB)")
    print("=" * 65)

    ensure_valid_session()
    new_count = sync_facebook_rentals(results_limit=25)
    push_to_github()

    print("\n✅ Hoàn tất quá trình đồng bộ Facebook.")


if __name__ == "__main__":
    main()
