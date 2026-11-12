"""
pipeline.py – Điều phối toàn bộ chu trình ETL:
  1. Thu thập dữ liệu từ fb_crawler + web_crawler (Phongtro123 & Chợ Tốt)
  2. Lọc URL trùng với SQLite
  3. Lọc rác & chuẩn hóa giá, quận, loại phòng bằng Regex thuần (ai_filter.py) – 0 tốn token
  4. Lưu bài hợp lệ vào SQLite
  5. Chạy tự động mỗi 30 phút bằng APScheduler (hoặc chạy 1 lần qua cờ --once)
"""

import logging
import sys
from datetime import datetime
from typing import Any, Dict, List

from apscheduler.schedulers.blocking import BlockingScheduler

from ai_filter import filter_and_extract
from database import cleanup_old_rentals, init_db, insert_rental, url_exists
from fb_crawler import crawl_fb_groups
from web_crawler import crawl_chotot, crawl_phongtro123

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("pipeline")


# ── Bước 1: Thu thập ─────────────────────────────────────────────────
def _collect_all() -> List[Dict[str, Any]]:
    """Gom dữ liệu từ tất cả các nguồn crawler."""
    all_items: List[Dict[str, Any]] = []

    # Facebook Groups
    try:
        fb_items = crawl_fb_groups()
        log.info("Facebook: thu được %d bài.", len(fb_items))
        all_items.extend(fb_items)
    except Exception as e:
        log.error("Lỗi khi cào Facebook: %s", e)

    # Sàn BĐS: mỗi nguồn lỗi độc lập, không làm hỏng nguồn khác
    for name, fn in (("Phongtro123", crawl_phongtro123), ("Chợ Tốt", crawl_chotot)):
        try:
            items = fn()
            log.info("%s: thu được %d bài.", name, len(items))
            all_items.extend(items)
        except Exception as e:
            log.error("Lỗi khi cào %s: %s", name, e)

    log.info("Tổng cộng thu thập: %d bài từ tất cả nguồn.", len(all_items))
    return all_items


# ── Bước 2: Lọc URL trùng ────────────────────────────────────────────
def _filter_new_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Chỉ giữ lại các bài có URL chưa tồn tại trong database."""
    new_items = []
    skipped = 0

    for item in items:
        url = item.get("url", "")
        if not url:
            continue
        if url_exists(url):
            skipped += 1
        else:
            new_items.append(item)

    log.info(
        "Lọc URL trùng: %d bài mới, %d bài đã có trong DB (bỏ qua).",
        len(new_items), skipped,
    )
    return new_items


# ── Bước 3 + 4: Phân tích Regex & lưu DB ─────────────────────────────
def _analyze_and_save(items: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Phân tích từng bài bằng regex/rule-based, chỉ lưu bài hợp lệ vào SQLite.
    Trả về thống kê {saved, spam, invalid, error}.
    """
    stats = {"saved": 0, "spam": 0, "invalid": 0, "error": 0}
    total = len(items)

    for i, item in enumerate(items, 1):
        title = item.get("title", "")
        raw_content = item.get("raw_content", "")

        try:
            analysis = filter_and_extract(title, raw_content, existing_data=item)
        except Exception as e:
            log.warning("Lỗi phân tích cho '%s': %s", title[:40], e)
            stats["error"] += 1
            continue

        # Chỉ lưu bài cho thuê hợp lệ, không phải spam/tin tìm trọ
        if not analysis.get("is_valid_rental"):
            log.info("[%d/%d] Bỏ qua (không phải tin cho thuê): %s", i, total, title[:40])
            stats["invalid"] += 1
            continue

        if analysis.get("is_spam"):
            log.info("[%d/%d] Bỏ qua (spam / giá ảo): %s", i, total, title[:40])
            stats["spam"] += 1
            continue

        # Merge dữ liệu crawler + phân tích → payload lưu DB
        record = {
            "title": title,
            "raw_content": raw_content,
            "price_vnd": analysis.get("price_vnd"),
            "district": analysis.get("district"),
            "room_type": analysis.get("room_type"),
            "url": item.get("url"),
            "source": item.get("source"),
            "posted_time": item.get("posted_time"),
            "created_at": datetime.now().isoformat(),
            "image_url": analysis.get("image_url") or item.get("image_url"),
            "phone": analysis.get("phone") or item.get("phone"),
            "area_m2": analysis.get("area_m2") if analysis.get("area_m2") is not None else item.get("area_m2"),
        }

        if insert_rental(record):
            price_display = f"{record['price_vnd']:,}đ" if record.get("price_vnd") else "Thỏa thuận"
            log.info(
                "[%d/%d] Đã lưu: %s | %s | %s | %s",
                i, total, record["district"], record["room_type"], price_display, title[:35]
            )
            stats["saved"] += 1
        else:
            log.info("[%d/%d] URL đã tồn tại: %s", i, total, record["url"])

    return stats


# ── Pipeline chính ────────────────────────────────────────────────────
def run_pipeline() -> None:
    """Chạy toàn bộ chu trình: Thu thập → Lọc trùng → Regex phân tích → Lưu DB."""
    start = datetime.now()
    log.info("═══ BẮT ĐẦU CHU TRÌNH PIPELINE ═══")

    # 1. Thu thập
    raw_items = _collect_all()
    if not raw_items:
        log.info("Không có bài đăng mới nào. Kết thúc chu trình.")
        return

    # 2. Lọc URL trùng (không quét lại tin cũ)
    new_items = _filter_new_items(raw_items)
    if not new_items:
        log.info("Tất cả URL đã có trong DB. Kết thúc chu trình.")
        return

    # 3 + 4. Phân tích & lưu
    stats = _analyze_and_save(new_items)

    # 5. Tự động dọn dẹp các tin đăng cũ hơn 14 ngày để giữ dung lượng DB nhỏ gọn (< 2MB)
    try:
        deleted = cleanup_old_rentals(days=14)
        if deleted > 0:
            log.info("Dọn dẹp DB: đã xóa %d tin đăng cũ hơn 14 ngày (VACUUM hoàn tất).", deleted)
    except Exception as e:
        log.warning("Lỗi dọn dẹp tin cũ trong DB: %s", e)

    elapsed = (datetime.now() - start).total_seconds()
    log.info(
        "═══ KẾT THÚC CHU TRÌNH (%.1fs) ═══  "
        "Đã lưu: %d | Spam: %d | Không hợp lệ: %d | Lỗi: %d",
        elapsed, stats["saved"], stats["spam"], stats["invalid"], stats["error"],
    )


# ── Scheduler ─────────────────────────────────────────────────────────
def main() -> None:
    init_db()
    log.info("Database sẵn sàng.")

    # Chạy một lần duy nhất nếu có cờ --once (gọi từ Streamlit Cloud hoặc CLI)
    if "--once" in sys.argv:
        log.info("Chế độ chạy một lần (--once). Bắt đầu quét...")
        run_pipeline()
        log.info("Hoàn tất quét một lần. Kết thúc tiến trình.")
        return

    # Chạy ngay lần đầu
    run_pipeline()

    # Lập lịch tự động mỗi 30 phút
    scheduler = BlockingScheduler()
    scheduler.add_job(run_pipeline, "interval", minutes=30, id="rental_pipeline")
    log.info("Scheduler kích hoạt. Chu kỳ: mỗi 30 phút.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Đã dừng pipeline scheduler.")
        sys.exit(0)


if __name__ == "__main__":
    main()
