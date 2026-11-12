"""
fb_crawler.py – Thu thập bài viết Facebook Groups cho thuê trọ Đà Nẵng bằng Playwright.
Hỗ trợ quản lý session & lưu trữ cookie đa môi trường (Local & Streamlit Cloud).
Kỹ thuật cuộn trang đa tầng, chống chặn, và bóc tách bài viết thông minh.
"""

import json
import logging
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("fb_crawler")

PROJECT_DIR = Path(__file__).resolve().parent
PROFILE_DIR = PROJECT_DIR / "fb_profile"
COOKIE_FILE = PROJECT_DIR / "fb_cookies.json"

# Danh sách Facebook Groups cho thuê phòng trọ Đà Nẵng công khai & sôi động nhất
DEFAULT_FB_GROUPS = [
    "https://www.facebook.com/groups/thuephongtrodanang",
    "https://www.facebook.com/groups/phongtrodanang",
    "https://www.facebook.com/groups/nhatrodanang",
    "https://www.facebook.com/groups/phongtrochothuedanang",
    "https://www.facebook.com/groups/timphongtrodanang",
    "https://www.facebook.com/groups/chothuephongtrocanhodanang",
    "https://www.facebook.com/groups/phongtrogiaredanang",
    "https://www.facebook.com/groups/333399913830339",  # Hội Tìm Phòng Trọ Đà Nẵng
]

DEFAULT_GROUP_URLS = DEFAULT_FB_GROUPS
DEFAULT_RESULTS_LIMIT = 25


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
      1. Biến môi trường FB_COOKIES_JSON (Ưu tiên trên Streamlit Cloud / GitHub Actions)
      2. File fb_cookies.json trên ổ đĩa (Local)
    """
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
    """
    Tìm đường dẫn chuẩn của bài viết trong thẻ feed.
    Làm sạch mọi query tracking (?__cft__..., &__tn__...) để tránh trùng URL.
    """
    try:
        for a in item.locator("a[href]").all():
            href = a.get_attribute("href") or ""
            if not href:
                continue

            # 1. Dạng /posts/123456789 hoặc /permalink/123456789
            m_post = re.search(r'/(?:posts|permalink)/(\d+)', href)
            if m_post:
                return f"https://www.facebook.com/groups/{group_slug}/posts/{m_post.group(1)}/"

            # 2. Dạng set=pcb.123456789
            m_pcb = re.search(r'set=pcb\.(\d+)', href)
            if m_pcb:
                return f"https://www.facebook.com/groups/{group_slug}/posts/{m_pcb.group(1)}/"

            # 3. Dạng story_fbid=123456789
            m_story = re.search(r'story_fbid=(\d+)', href)
            if m_story:
                return f"https://www.facebook.com/groups/{group_slug}/posts/{m_story.group(1)}/"

            # 4. Dạng multi_permalinks=123456789
            m_multi = re.search(r'multi_permalinks=(\d+)', href)
            if m_multi:
                return f"https://www.facebook.com/groups/{group_slug}/posts/{m_multi.group(1)}/"
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
                if len(t) > 20 and not any(w in t for w in ["Bình luận", "Chia sẻ", "Thích", "Xem thêm", "Tất cả bình luận"]):
                    texts.append(t)
            except Exception:
                continue
        if texts:
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


def _extract_post_image(item) -> Optional[str]:
    """
    Trích xuất link ảnh bài viết từ Facebook.
    Chỉ lấy ảnh nội dung (scontent/fbcdn), bỏ qua ảnh avatar tác giả và icon emoji.
    """
    try:
        imgs = item.locator("img").all()
        for img in imgs:
            src = img.get_attribute("src") or ""
            if not src or not ("scontent" in src or "fbcdn" in src):
                continue
            if any(x in src for x in ["/rsrc.php/", "emoji.php", "/assets/"]):
                continue

            alt = (img.get_attribute("alt") or "").lower()
            if "ảnh đại diện" in alt or "avatar" in alt:
                continue

            try:
                box = img.bounding_box()
                if box and (box["width"] < 70 or box["height"] < 70):
                    continue
            except Exception:
                pass

            return src
    except Exception:
        pass
    return None


def _extract_posts(page, group_url: str, limit: int = DEFAULT_RESULTS_LIMIT, max_scrolls: int = 8) -> List[Dict[str, Any]]:
    """
    Cuộn trang 6–8 lần, tự động click 'Xem thêm', trích xuất bài đăng và lọc trùng link.
    Delay ngẫu nhiên giữa các lần cuộn để mô phỏng hành vi người dùng thật.
    """
    posts: Dict[str, Dict[str, Any]] = {}
    group_slug = _extract_group_slug(group_url)

    for scroll_idx in range(max_scrolls):
        # Bấm các nút "Xem thêm" / "See more" để bung nội dung bài viết
        try:
            more_buttons = page.locator(
                "div[role='button']:has-text('Xem thêm'), "
                "span:has-text('Xem thêm'), "
                "div[role='button']:has-text('See more'), "
                "span:has-text('See more')"
            ).all()
            for btn in more_buttons[:8]:
                try:
                    btn.click(timeout=300)
                except Exception:
                    pass
        except Exception:
            pass

        # Quét các thẻ bài viết (role='article', role='feed' > div, container chứa message)
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

                title = text.split("\n")[0][:60].strip() or text[:60].strip()
                image_url = _extract_post_image(item)

                posts[post_url] = {
                    "title": title,
                    "raw_content": text,
                    "url": post_url,
                    "source": "Facebook",
                    "posted_time": datetime.now().isoformat(),
                    "image_url": image_url,
                }
            except Exception:
                continue

        if len(posts) >= limit:
            break

        # Cuộn trang xuống kèm delay ngẫu nhiên 1.5s - 3s
        scroll_y = random.randint(2500, 3500)
        page.mouse.wheel(0, scroll_y)
        wait_time = random.uniform(1.5, 3.0)
        page.wait_for_timeout(int(wait_time * 1000))

    return list(posts.values())[:limit]


def crawl_fb_groups(
    group_urls: Optional[List[str]] = None,
    results_limit: int = DEFAULT_RESULTS_LIMIT,
    headless: bool = True,
) -> List[Dict[str, Any]]:
    """
    Cào bài viết từ các Facebook Group phòng trọ Đà Nẵng.
    Kỹ thuật chống chặn đa tầng, log chẩn đoán chi tiết.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        log.warning("Thư viện playwright chưa được cài đặt: %s. Bỏ qua cào Facebook.", e)
        return []

    urls = group_urls or [
        u.strip() for u in os.getenv("FB_GROUP_URLS", "").split(",") if u.strip()
    ] or DEFAULT_FB_GROUPS

    cookies = get_persisted_cookies()
    results: List[Dict[str, Any]] = []

    try:
        with sync_playwright() as p:
            browser = None
            try:
                browser = p.chromium.launch(
                    headless=headless,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-notifications",
                        "--disable-geolocation",
                    ],
                )
            except Exception as e:
                err_msg = str(e).lower()
                if "executable" in err_msg or "install" in err_msg:
                    log.info("Chưa có browser binary trên Cloud, đang chạy 'playwright install chromium'...")
                    try:
                        import subprocess
                        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True, timeout=120)
                        browser = p.chromium.launch(
                            headless=headless,
                            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                        )
                    except Exception as err:
                        log.warning("Không thể tự động cài Playwright Chromium: %s", err)

                if browser is None:
                    log.warning("Chromium không thể khởi chạy trên môi trường hiện tại: %s", e)
                    return []

            ctx = browser.new_context(
                locale="vi-VN",
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
                timezone_id="Asia/Ho_Chi_Minh",
            )
            ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            # Nạp cookies nếu có
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
                    page.wait_for_timeout(random.randint(2000, 3500))

                    page_title = page.title()
                    current_url = page.url
                    log.info("  → URL hiện tại: %s | Tiêu đề: '%s'", current_url, page_title)

                    # Chẩn đoán trang
                    if "checkpoint" in current_url:
                        log.warning("  ⚠️ Nhóm/Tài khoản gặp trang checkpoint bảo mật: %s", current_url)
                        continue

                    if "login" in current_url or page.locator("input[name='pass'], input[type='password']").count() > 0:
                        log.warning(
                            "  ⚠️ Facebook yêu cầu đăng nhập đối với %s. "
                            "Hãy chạy 'python3 fb_crawler.py --login' để cập nhật session.",
                            url,
                        )
                        continue

                    body_snippet = page.locator("body").inner_text()
                    if "Tham gia nhóm" in body_snippet or "Join group" in body_snippet:
                        log.info("  ℹ️ Nhóm yêu cầu quyền thành viên (Tham gia nhóm). Đang kiểm tra bài viết công khai...")

                    items = _extract_posts(page, group_url=url, limit=results_limit, max_scrolls=8)
                    log.info("  → Thu thập được %d bài viết từ %s", len(items), url)
                    results.extend(items)
                except Exception as e:
                    log.error("Lỗi khi cào %s: %s", url, e)

            browser.close()
    except Exception as e:
        log.error("Lỗi Playwright trong fb_crawler: %s", e)
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
    print("3. Hệ thống sẽ tự động phát hiện cookie khi đăng nhập thành công,")
    print("   hoặc bạn có thể nhấn ENTER tại terminal sau khi đăng nhập xong.")
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

        start_time = time.time()
        logged_in = False

        while time.time() - start_time < 300:  # Chờ tối đa 5 phút
            current_cookies = ctx.cookies()
            # Kiểm tra cả c_user và xs
            has_c_user = any(c.get("name") == "c_user" for c in current_cookies)
            has_xs = any(c.get("name") == "xs" for c in current_cookies)

            if has_c_user and has_xs and "login" not in page.url:
                print("\n✅ Phát hiện đăng nhập thành công qua cookie 'c_user' và 'xs'!")
                logged_in = True
                time.sleep(2)
                break

            time.sleep(1)

        # Xuất cookies ra file json
        all_cookies = ctx.cookies()
        with open(COOKIE_FILE, "w", encoding="utf-8") as f:
            json.dump(all_cookies, f, ensure_ascii=False, indent=2)

        print(f"\n✅ Đã lưu {len(all_cookies)} cookies vào file {COOKIE_FILE.name}")
        ctx.close()


if __name__ == "__main__":
    if "--login" in sys.argv:
        login_interactive()
    else:
        data = crawl_fb_groups(results_limit=10)
        print(f"\n== Tổng cộng thu được {len(data)} bài viết Facebook ==")
        for p in data[:3]:
            print(f"[{p['posted_time']}] {p['title']}")
            print("   URL:  ", p["url"])
