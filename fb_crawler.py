"""
fb_crawler.py – Thu thập bài viết từ Facebook Group cho thuê trọ Đà Nẵng
thông qua Apify Actor (facebook-groups-scraper).
"""

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from apify_client import ApifyClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# Danh sách URL các Facebook Group cho thuê trọ Đà Nẵng
DEFAULT_GROUP_URLS = [
    "https://www.facebook.com/groups/thuephongtrodanang",
    "https://www.facebook.com/groups/phongtrodanang",
    "https://www.facebook.com/groups/nhatrodanang",
]

DEFAULT_ACTOR_ID = "apify/facebook-groups-scraper"
DEFAULT_RESULTS_LIMIT = 20


def _get_client() -> ApifyClient:
    token = os.getenv("APIFY_TOKEN")
    if not token:
        raise RuntimeError(
            "Thiếu biến môi trường APIFY_TOKEN. "
            "Hãy đặt token tại https://console.apify.com/account#/integrations"
        )
    return ApifyClient(token=token)


def _parse_posted_time(raw_time: Any) -> Optional[str]:
    """Chuẩn hóa trường thời gian từ Apify về ISO 8601."""
    if raw_time is None:
        return None

    if isinstance(raw_time, datetime):
        return raw_time.isoformat()

    if isinstance(raw_time, str):
        # Apify thường trả ISO string hoặc timestamp dạng "2026-11-12T08:30:00.000Z"
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(raw_time, fmt).isoformat()
            except ValueError:
                continue
        # Trả nguyên chuỗi nếu không parse được — tốt hơn mất dữ liệu
        return raw_time

    if isinstance(raw_time, (int, float)):
        # Unix timestamp (giây)
        return datetime.utcfromtimestamp(raw_time).isoformat()

    return None


def _normalize_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Chuẩn hóa một bản ghi từ dataset Apify thành dictionary thống nhất
    phục vụ lưu vào bảng `rentals` trong database.py.
    """
    text = item.get("text") or item.get("message") or item.get("postText") or ""
    post_url = (
        item.get("url")
        or item.get("postUrl")
        or item.get("link")
        or ""
    )
    raw_time = (
        item.get("time")
        or item.get("date")
        or item.get("postedAt")
        or item.get("timestamp")
    )

    return {
        "title": text[:50].replace("\n", " ").strip() if text else "",
        "raw_content": text,
        "url": post_url,
        "source": "Facebook",
        "posted_time": _parse_posted_time(raw_time),
    }


def crawl_fb_groups(
    group_urls: Optional[List[str]] = None,
    results_limit: int = DEFAULT_RESULTS_LIMIT,
    actor_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Gọi Apify Actor để cào bài viết mới nhất từ danh sách Facebook Group.

    Args:
        group_urls: Danh sách URL group. Mặc định dùng DEFAULT_GROUP_URLS.
        results_limit: Số bài viết tối đa mỗi group (mặc định 20).
        actor_id: ID của Apify Actor. Mặc định lấy từ biến môi trường
                  APIFY_ACTOR_ID hoặc fallback "apify/facebook-groups-scraper".

    Returns:
        Danh sách dict đã chuẩn hóa, sẵn sàng truyền vào insert_rental().
    """
    urls = group_urls or DEFAULT_GROUP_URLS
    actor = actor_id or os.getenv("APIFY_ACTOR_ID", DEFAULT_ACTOR_ID)
    client = _get_client()

    run_input = {
        "startUrls": [{"url": u} for u in urls],
        "resultsLimit": results_limit,
    }

    logging.info(
        "Khởi chạy Actor '%s' cho %d group, tối đa %d bài/group...",
        actor, len(urls), results_limit,
    )

    run = client.actor(actor).call(run_input=run_input)

    dataset_id = run.get("defaultDatasetId")
    if not dataset_id:
        logging.warning("Actor chạy xong nhưng không có dataset. Run info: %s", run)
        return []

    raw_items = list(client.dataset(dataset_id).iterate_items())
    logging.info("Nhận %d bản ghi thô từ Apify dataset.", len(raw_items))

    results: List[Dict[str, Any]] = []
    for item in raw_items:
        normalized = _normalize_item(item)
        # Bỏ qua bài viết rỗng hoặc không có URL
        if normalized["raw_content"] and normalized["url"]:
            results.append(normalized)

    logging.info(
        "Chuẩn hóa xong: %d/%d bài viết hợp lệ (có nội dung + URL).",
        len(results), len(raw_items),
    )
    return results


if __name__ == "__main__":
    posts = crawl_fb_groups()
    for i, post in enumerate(posts[:3], 1):
        print(f"\n--- Bài #{i} ---")
        print(f"  Title:  {post['title']}")
        print(f"  URL:    {post['url']}")
        print(f"  Source: {post['source']}")
        print(f"  Time:   {post['posted_time']}")
        print(f"  Content ({len(post['raw_content'])} chars): {post['raw_content'][:120]}...")
    print(f"\nTổng cộng: {len(posts)} bài viết.")
