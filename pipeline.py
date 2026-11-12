"""
pipeline.py – Điều phối toàn bộ chu trình:
  1. Thu thập dữ liệu từ fb_crawler + web_crawler
  2. Lọc URL trùng với database (tiết kiệm token OpenRouter)
  3. Phân tích qua ai_filter (OpenRouter)
  4. Lưu bài hợp lệ vào SQLite
  5. Chạy tự động mỗi 30 phút bằng APScheduler
"""

import logging
import sys
from datetime import datetime
from typing import Any, Dict, List

from apscheduler.schedulers.blocking import BlockingScheduler

from ai_filter import QuotaExceededError, analyze_rental
from database import init_db, insert_rental, url_exists
from fb_crawler import crawl_fb_groups
from web_crawler import crawl_chotot, crawl_phongtro123

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("pipeline")


# ── Bước 1: Thu thập ─────────────────────────────────────────────────
def _collect_all() -> List[Dict[str, Any]]:
    """Gom dữ liệu thô từ tất cả nguồn crawler."""
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


# ── Bước 3 + 4: Phân tích AI & lưu DB ────────────────────────────────
def _analyze_and_save(items: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Gửi từng bài qua OpenRouter để phân loại, chỉ lưu bài hợp lệ vào SQLite.
    Nếu gặp QuotaExceededError (402, 401, 429), break dừng ngay chu trình và
    không lưu URL của các bài bị lỗi vào database để xử lý lại lần sau.
    Trả về thống kê {saved, spam, invalid, error}.
    """
    stats = {"saved": 0, "spam": 0, "invalid": 0, "error": 0}
    total = len(items)

    for i, item in enumerate(items, 1):
        title = item.get("title", "")
        raw_content = item.get("raw_content", "")

        log.info("[%d/%d] Phân tích: %s", i, total, title[:50])

        try:
            analysis = analyze_rental(title, raw_content)
        except QuotaExceededError as e:
            log.error(
                "DỪNG CHU TRÌNH: OpenRouter hết credit hoặc lỗi API key (%s). "
                "Bỏ qua %d tin còn lại để xử lý lại ở chu trình sau.",
                e, total - i + 1,
            )
            stats["error"] += (total - i + 1)
            break
        except Exception as e:
            log.warning("Lỗi không mong muốn khi gọi AI cho '%s': %s", title[:40], e)
            stats["error"] += 1
            continue

        # Chỉ lưu bài cho thuê hợp lệ, không phải spam
        if not analysis.get("is_valid_rental"):
            log.info("  → Bỏ qua (không phải tin cho thuê)")
            stats["invalid"] += 1
            continue

        if analysis.get("is_spam"):
            log.info("  → Bỏ qua (spam / giá ảo)")
            stats["spam"] += 1
            continue

        # Merge dữ liệu crawler + AI analysis → payload lưu DB
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
        }

        if insert_rental(record):
            log.info("  → Đã lưu: %s | %s | %s",
                     analysis.get("district"), analysis.get("room_type"),
                     f"{analysis.get('price_vnd'):,}đ" if analysis.get("price_vnd") else "N/A")
            stats["saved"] += 1
        else:
            # insert_rental trả False nếu URL duplicate
            log.info("  → URL đã tồn tại (bỏ qua)")

    return stats


# ── Pipeline chính ────────────────────────────────────────────────────
def run_pipeline() -> None:
    """Chạy toàn bộ chu trình: Thu thập → Lọc trùng → AI phân tích → Lưu DB."""
    start = datetime.now()
    log.info("═══ BẮT ĐẦU CHU TRÌNH PIPELINE ═══")

    # 1. Thu thập
    raw_items = _collect_all()
    if not raw_items:
        log.info("Không có bài đăng mới nào. Kết thúc chu trình.")
        return

    # 2. Lọc URL trùng (tiết kiệm token OpenRouter)
    new_items = _filter_new_items(raw_items)
    if not new_items:
        log.info("Tất cả URL đã có trong DB. Không cần gọi AI. Kết thúc chu trình.")
        return

    # 3 + 4. Phân tích AI & lưu
    stats = _analyze_and_save(new_items)

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
