"""
fb_crawler.py – Thu thập bài viết Facebook Groups cho thuê trọ Đà Nẵng bằng Playwright.
Hỗ trợ quản lý session & lưu trữ cookie đa môi trường (Local & Streamlit Cloud).

Cách sử dụng:
  1. Đăng nhập 1 lần trên máy local:
     python3 fb_crawler.py --login
     -> Session lưu vào fb_profile/ và xuất ra fb_cookies.json

  2. Triển khai Streamlit Cloud:
     Sao chép nội dung fb_cookies.json vào Streamlit Secrets:
     FB_COOKIES_JSON = '''[ ... ]'''

  3. Chạy cào dữ liệu:
     python3 fb_crawler.py
"""

import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("fb_crawler")

PROJECT_DIR = Path(__file__).resolve().parent
PROFILE_DIR = PROJECT_DIR / "fb_profile"
COOKIE_FILE = PROJECT_DIR / "fb_cookies.json"

DEFAULT_GROUP_URLS = [
    "https://www.facebook.com/groups/thuephongtrodanang",
    "https://www.facebook.com/groups/phongtrodanang",
    "https://www.facebook.com/groups/nhatrodanang",
]

DEFAULT_RESULTS_LIMIT = 20
POST_LINK_RE = re.compile(r"/(posts|permalink)/\d+|story_fbid=|/groups/[^/]+/posts/|set=pcb\.\d+")


def _sanitize_cookie(c: Dict[str, Any]) -> Dict[str, Any]:
    """Làm sạch và chuẩn hóa định dạng cookie phù hợp với Playwright."""
    cookie: Dict[str, Any] = {
        "name": c["name"],
        "value": c["value"],
        "domain": c.get("domain", ".facebook.com"),
        "path": c.get("path", "/"),
    }
    if "expires" in c and isinstance(c["expires"], (int, float)):
        cookie["expires"] = c["expires"]
    if "httpOnly" in c:
        cookie["httpOnly"] = bool(c["httpOnly"])
    if "secure" in c:
        cookie["secure"] = bool(c["secure"])
    if "sameSite" in c and c["sameSite"]:
        same_site = str(c["sameSite"]).capitalize()
        if same_site in ("Strict", "Lax", "None"):
            cookie["sameSite"] = same_site
    return cookie


def get_persisted_cookies() -> List[Dict[str, Any]]:
    """
    Nạp cookies từ:
      1. Biến môi trường FB_COOKIES_JSON (Ưu tiên trên Streamlit Cloud)
      2. File fb_cookies.json trên ổ đĩa (Local)
    """
    # 1. Từ biến môi trường
    env_cookies = os.getenv("FB_COOKIES_JSON")
    if env_cookies:
        try:
            parsed = json.loads(env_cookies)
            if isinstance(parsed, list):
                valid = [_sanitize_cookie(c) for c in parsed if isinstance(c, dict) and "name" in c and "value" in c]
                if valid:
                    log.info("Đã nạp %d cookies từ biến môi trường FB_COOKIES_JSON.", len(valid))
                    return valid
        except Exception as e:
            log.warning("Không thể parse FB_COOKIES_JSON từ biến môi trường: %s", e)

    # 2. Từ file cục bộ
    if COOKIE_FILE.exists():
        try:
            with open(COOKIE_FILE, "r", encoding="utf-8") as f:
                parsed = json.load(f)
                if isinstance(parsed, list):
                    valid = [_sanitize_cookie(c) for c in parsed if isinstance(c, dict) and "name" in c and "value" in c]
                    if valid:
                        log.info("Đã nạp %d cookies từ file %s.", len(valid), COOKIE_FILE.name)
                        return valid
        except Exception as e:
            log.warning("Lỗi khi đọc file %s: %s", COOKIE_FILE.name, e)

    return []


def _extract_group_slug(group_url: str) -> str:
    """Trích xuất slug hoặc id của group từ URL."""
    m = re.search(r'/groups/([^/?#]+)', group_url)
    return m.group(1) if m else "group"


def _extract_post_url(item, group_slug: str) -> Optional[str]:
    """Tìm đường dẫn chuẩn của bài viết trong thẻ feed."""
    try:
        for a in item.locator("a[href]").all():
            href = a.get_attribute("href") or ""
            # Dạng set=pcb.123456789
            m_pcb = re.search(r'set=pcb\.(\d+)', href)
            if m_pcb:
                return f"https://www.facebook.com/groups/{group_slug}/posts/{m_pcb.group(1)}/"

            # Dạng /posts/123456789 hoặc /permalink/123456789
            m_post = re.search(r'/(?:posts|permalink)/(\d+)', href)
            if m_post:
                return f"https://www.facebook.com/groups/{group_slug}/posts/{m_post.group(1)}/"

            # Dạng story_fbid=123456789
            m_story = re.search(r'story_fbid=(\d+)', href)
            if m_story:
                return f"https://www.facebook.com/groups/{group_slug}/posts/{m_story.group(1)}/"
    except Exception:
        pass
    return None


def _extract_post_text(item) -> str:
    """Lấy nội dung văn bản bài viết, ưu tiên vùng nội dung chính."""
    # 1. Thử qua data-ad-preview message
    try:
        msg = item.locator("div[data-ad-preview='message'], div[data-ad-comet-preview='message']").first
        if msg.count() > 0:
            txt = msg.inner_text().strip()
            if len(txt) > 10:
                return txt
    except Exception:
        pass

    # 2. Thử các khối dir='auto'
    try:
        divs = item.locator("div[dir='auto']").all()
        texts = []
        for d in divs:
            try:
                t = d.inner_text().strip()
                if len(t) > 20 and not any(w in t for w in ["Bình luận", "Chia sẻ", "Thích", "Xem thêm"]):
                    texts.append(t)
            except Exception:
                continue
        if texts:
            # Lấy đoạn dài nhất
            texts.sort(key=len, reverse=True)
            return texts[0]
    except Exception:
        pass

    # 3. Fallback lấy toàn bộ text thẻ
    try:
        raw = item.inner_text().strip()
        lines = [line.strip() for line in raw.split("\n") if len(line.strip()) > 15]
        return "\n".join(lines)
    except Exception:
        return ""


def _extract_posts(page, group_url: str, limit: int, max_scrolls: int = 4) -> List[Dict[str, Any]]:
    """Cuộn trang 3-5 lần, bấm 'Xem thêm', trích xuất bài đăng và lọc trùng link."""
    posts: Dict[str, Dict[str, Any]] = {}
    group_slug = _extract_group_slug(group_url)

    for _ in range(max_scrolls):
        # Bấm các nút "Xem thêm" / "See more" để bung nội dung ẩn
        try:
            buttons = page.get_by_role("button", name=re.compile(r"Xem thêm|See more|Xem thêm bài viết", re.I)).all()
            for btn in buttons[:6]:
                try:
                    btn.click(timeout=500)
                except Exception:
                    pass
        except Exception:
            pass

        # Quét các thẻ bài viết (div[role='feed'] > div hoặc role='article')
        try:
            items = page.locator("div[role='feed'] > div, div[role='article']").all()
        except Exception:
            items = []

        for item in items:
            try:
                post_url = _extract_post_url(item, group_slug)
                if not post_url or post_url in posts:
                    continue

                text = _extract_post_text(item)
                if not text or len(text) < 20:
                    continue

                title = text.split("\n")[0][:50].strip() or text[:50].strip()

                posts[post_url] = {
                    "title": title,
                    "raw_content": text,
                    "url": post_url,
                    "source": "Facebook",
                    "posted_time": datetime.now().isoformat(),
                }
            except Exception:
                continue

        if len(posts) >= limit:
            break

        # Cuộn trang xuống
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(2000)

    return list(posts.values())[:limit]


def crawl_fb_groups(
    group_urls: Optional[List[str]] = None,
    results_limit: int = DEFAULT_RESULTS_LIMIT,
    headless: bool = True,
) -> List[Dict[str, Any]]:
    """
    Cào bài viết từ các Facebook Group.
    Tự động nạp cookie/session từ biến môi trường hoặc file fb_cookies.json.
    An toàn 100%: nếu thiếu Chromium trên Cloud thì chỉ log cảnh báo và trả về [].
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        log.warning("Thư viện playwright chưa được cài đặt: %s. Bỏ qua cào Facebook.", e)
        return []

    urls = group_urls or [
        u.strip() for u in os.getenv("FB_GROUP_URLS", "").split(",") if u.strip()
    ] or DEFAULT_GROUP_URLS

    cookies = get_persisted_cookies()
    results: List[Dict[str, Any]] = []

    try:
        with sync_playwright() as p:
            ctx = None
            try:
                ctx = p.chromium.launch_persistent_context(
                    str(PROFILE_DIR),
                    headless=headless,
                    locale="vi-VN",
                    args=["--disable-notifications", "--disable-geolocation"],
                )
            except Exception as e:
                err_msg = str(e).lower()
                if "executable" in err_msg or "install" in err_msg:
                    log.info("Chưa có browser binary trên Cloud, đang tự động chạy 'playwright install chromium'...")
                    try:
                        import subprocess
                        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True, timeout=120)
                        ctx = p.chromium.launch_persistent_context(
                            str(PROFILE_DIR),
                            headless=headless,
                            locale="vi-VN",
                            args=["--disable-notifications", "--disable-geolocation"],
                        )
                    except Exception as err:
                        log.warning("Không thể tự động cài Playwright Chromium: %s", err)

                if ctx is None:
                    log.warning("Không thể mở persistent_context, fallback sang browser thông thường: %s", e)
                    try:
                        browser = p.chromium.launch(
                            headless=headless,
                            args=["--disable-notifications", "--disable-geolocation"],
                        )
                        ctx = browser.new_context(locale="vi-VN")
                    except Exception as ex:
                        log.warning("Chromium không khả dụng trên môi trường hiện tại: %s", ex)
                        return []

            # Nạp cookie nếu có
            if cookies:
                try:
                    ctx.add_cookies(cookies)
                except Exception as e:
                    log.warning("Lỗi nạp cookies vào context: %s", e)

            page = ctx.new_page()

            for url in urls:
                try:
                    log.info("Mở Facebook group: %s", url)
                    page.goto(url, wait_until="domcontentloaded", timeout=25000)
                    page.wait_for_timeout(2500)

                    # Kiểm tra trang bắt đăng nhập
                    if "login" in page.url or page.locator("input[name='pass']").count() > 0:
                        log.warning(
                            "Facebook yêu cầu đăng nhập đối với %s. "
                            "Hãy chạy 'python3 fb_crawler.py --login' để cập nhật session.",
                            url,
                        )
                        continue

                    items = _extract_posts(page, group_url=url, limit=results_limit, max_scrolls=4)
                    log.info("  → Thu thập được %d bài viết từ %s", len(items), url)
                    results.extend(items)
                except Exception as e:
                    log.error("Lỗi khi cào %s: %s", url, e)

            ctx.close()
    except Exception as e:
        log.warning("Lỗi trong quá trình chạy Playwright Facebook crawler: %s", e)
        return []

    return results


def login_interactive() -> None:
    """
    Chế độ đăng nhập có giao diện để người dùng đăng nhập tài khoản 1 lần.
    Tự động phát hiện khi đăng nhập thành công và xuất cookies ra fb_cookies.json.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        print(f"Lỗi: Playwright chưa được cài đặt: {e}")
        return

    print("\n" + "=" * 65)
    print("  HƯỚNG DẪN ĐĂNG NHẬP FACEBOOK CHO DANANG RENTAL AGGREGATOR")
    print("=" * 65)
    print("1. Trình duyệt Chromium có giao diện sẽ tự động mở lên.")
    print("2. Đăng nhập tài khoản Facebook của bạn (nên dùng tài khoản phụ).")
    print("3. Hệ thống sẽ tự động phát hiện cookie 'c_user' khi đăng nhập thành công,")
    print("   hoặc bạn có thể nhấn ENTER tại đây sau khi đã đăng nhập xong.")
    print("4. Toàn bộ session sẽ được lưu vào fb_profile/ và fb_cookies.json.")
    print("=" * 65 + "\n")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,
            locale="vi-VN",
            viewport={"width": 1280, "height": 800},
            args=["--disable-notifications"],
        )
        page = ctx.new_page()
        page.goto("https://www.facebook.com/")

        print("Đang chờ đăng nhập trên trình duyệt...")
        import select

        start_time = time.time()
        logged_in = False

        while time.time() - start_time < 300:  # Chờ tối đa 5 phút
            # 1. Tự động kiểm tra cookie đăng nhập
            current_cookies = ctx.cookies()
            if any(c.get("name") == "c_user" for c in current_cookies):
                print("\n✅ Phát hiện đăng nhập thành công qua cookie 'c_user'!")
                logged_in = True
                time.sleep(2)  # Đợi thêm chút để các cookie phụ ghi đầy đủ
                break

            # 2. Hoặc người dùng gõ Enter ở terminal
            try:
                if sys.stdin in select.select([sys.stdin], [], [], 1.5)[0]:
                    sys.stdin.readline()
                    print("\n✅ Xác nhận người dùng đã đăng nhập xong!")
                    logged_in = True
                    break
            except Exception:
                time.sleep(1.5)

        # Xuất toàn bộ cookies ra file
        cookies = ctx.cookies()
        with open(COOKIE_FILE, "w", encoding="utf-8") as f:
            json.dump(cookies, f, indent=2, ensure_ascii=False)

        print("\n" + "=" * 65)
        print(f"🎉 HOÀN TẤT ĐĂNG NHẬP:")
        print(f" • Session Profile: {PROFILE_DIR}")
        print(f" • File Cookies:    {COOKIE_FILE} ({len(cookies)} cookies)")
        print("\n💡 HƯỚNG DẪN CẤU HÌNH CHO STREAMLIT CLOUD:")
        print("Sao chép nội dung file fb_cookies.json và dán vào phần Secrets trên Streamlit Cloud:")
        print("FB_COOKIES_JSON = '''[paste JSON ở đây]'''")
        print("=" * 65 + "\n")

        ctx.close()


if __name__ == "__main__":
    if "--login" in sys.argv:
        login_interactive()
    else:
        posts = crawl_fb_groups(headless="--show" not in sys.argv)
        for post in posts[:3]:
            print(f"[{post['posted_time']}] {post['url']}")
            print("   Title:", post["title"])
        print(f"Tổng cộng: {len(posts)} bài viết.")
