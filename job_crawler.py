"""
job_crawler.py – Thu thập và bóc tách dữ liệu việc làm tại Đà Nẵng (0 tốn token AI).
Nguồn dữ liệu:
  1. Việc Làm Tốt / Chợ Tốt Việc Làm (JSON API gateway.chotot.com, region_v2=3017, cg=13010)
  2. Vieclamdanang.vn (HTML trang chủ việc làm Đà Nẵng)
  3. Danang43.vn (HTML chuyên mục việc làm Đà Nẵng)
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ai_filter import extract_phone
from web_crawler import HEADERS, TIMEOUT, normalize_district

log = logging.getLogger("job_crawler")

JOB_CATEGORIES = {
    "Kỹ thuật / IT": [
        "it", "lập trình", "developer", "dev", "tester", "qa", "kỹ sư", "kỹ thuật",
        "cơ khí", "cơ điện", "điện lạnh", "bảo trì", "thi công", "xây dựng", "kiến trúc",
        "autocad", "designer", "thiết kế", "editor", "quay dựng",
    ],
    "Nhà hàng / Khách sạn / F&B": [
        "phục vụ", "pha chế", "barista", "bartender", "bếp", "phụ bếp", "đầu bếp",
        "lễ tân", "buồng phòng", "housekeeping", "khách sạn", "hotel", "resort",
        "nhà hàng", "quán ăn", "cafe", "trà sữa", "thu ngân", "tạp vụ", "spa", "massage",
    ],
    "Văn phòng / Kinh doanh": [
        "kinh doanh", "sale", "sales", "tư vấn", "cskh", "chăm sóc khách hàng",
        "kế toán", "hành chính", "nhân sự", "hr", "marketing", "content", "admin",
        "văn phòng", "thư ký", "trợ lý", "telesale", "bất động sản", "giáo viên", "gia sư",
    ],
    "Lao động phổ thông / Kho": [
        "công nhân", "lao động phổ thông", "lđpt", "kho", "thủ kho", "giao hàng",
        "shipper", "tài xế", "lái xe", "bốc xếp", "bảo vệ", "vệ sinh", "sản xuất",
        "đóng gói", "may mặc", "thợ hàn", "thợ mộc", "thợ sơn", "phụ xe",
    ],
    "Bán thời gian / Thời vụ": [
        "part time", "part-time", "bán thời gian", "thời vụ", "theo ca", "ca sáng",
        "ca chiều", "ca tối", "sinh viên", "ctv", "cộng tác viên",
    ],
}


def classify_job_type(title: str, content: str = "") -> str:
    """Phân loại ngành nghề dựa trên từ khóa trong tiêu đề và mô tả."""
    combined = f"{title} {content}".lower()
    for category, keywords in JOB_CATEGORIES.items():
        if any(kw in combined for kw in keywords):
            return category
    return "Khác"


def parse_salary_range(text: str) -> Tuple[Optional[int], Optional[int], str]:
    """
    Bóc tách mức lương từ chuỗi tiếng Việt sang (min_vnd, max_vnd, salary_text).
    Hỗ trợ: "10 - 15 triệu", "8tr", "8.5 triệu", "Thỏa thuận", "25k/giờ".
    """
    if not text:
        return None, None, "Thỏa thuận"

    clean = " ".join(text.split())
    lower = clean.lower()

    if any(w in lower for w in ("thỏa thuận", "thương lượng", "cạnh tranh")):
        return None, None, "Thỏa thuận"

    # Dạng khoảng: "10 - 15 triệu" hoặc "10-15tr"
    m_range = re.search(
        r"(\d+(?:[.,]\d+)?)\s*[-–~đến]+\s*(\d+(?:[.,]\d+)?)\s*(?:triệu|trieu|tr)\b",
        lower,
    )
    if m_range:
        v1 = int(float(m_range.group(1).replace(",", ".")) * 1_000_000)
        v2 = int(float(m_range.group(2).replace(",", ".")) * 1_000_000)
        return min(v1, v2), max(v1, v2), clean

    # Dạng một mức: "từ 8 triệu", "8.5 triệu", "12tr"
    m_single = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:triệu|trieu|tr)\b", lower)
    if m_single:
        v = int(float(m_single.group(1).replace(",", ".")) * 1_000_000)
        return v, v, clean

    # Dạng số VND đầy đủ (ví dụ "8.000.000 đ")
    m_full = re.search(r"(\d{1,2})[.,](\d{3})[.,]000", lower)
    if m_full:
        v = int(m_full.group(1) + m_full.group(2) + "000")
        return v, v, clean

    return None, None, clean


def crawl_chotot_jobs(limit: int = 40) -> List[Dict[str, Any]]:
    """Thu thập tin tuyển dụng tại Đà Nẵng từ Chợ Tốt / Việc Làm Tốt JSON API."""
    api_url = (
        f"https://gateway.chotot.com/v1/public/ad-listing"
        f"?region_v2=3017&cg=13010&limit={limit}&st=s,k"
    )
    results: List[Dict[str, Any]] = []
    try:
        resp = requests.get(api_url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        ads = resp.json().get("ads", [])
    except Exception as e:
        log.warning("Lỗi gọi API Việc Làm Tốt (Chợ Tốt): %s", e)
        return []

    for ad in ads:
        try:
            list_id = ad.get("list_id")
            subject = (ad.get("subject") or "").strip()
            if not list_id or not subject:
                continue

            body = (ad.get("body") or "").strip()
            company = (ad.get("company_name") or ad.get("account_name") or "Nhà tuyển dụng").strip()
            price_val = ad.get("price")
            price_str = (ad.get("price_string") or "").strip()

            if isinstance(price_val, (int, float)) and price_val > 100_000:
                sal_min = sal_max = int(price_val)
                sal_text = price_str or f"{sal_min // 1_000_000} triệu/tháng"
            else:
                sal_min, sal_max, sal_text = parse_salary_range(price_str or body)

            area_raw = f"{ad.get('ward_name') or ''} {ad.get('area_name') or ''}".strip()
            district = normalize_district(area_raw) or normalize_district(f"{subject} {body}") or "Đà Nẵng"

            list_time = ad.get("list_time")
            posted_time = (
                datetime.fromtimestamp(list_time / 1000).isoformat()
                if isinstance(list_time, (int, float)) and list_time > 0
                else datetime.now().isoformat()
            )

            image_url = ad.get("image")
            if not image_url and isinstance(ad.get("images"), list) and ad["images"]:
                image_url = ad["images"][0]

            results.append(
                {
                    "title": subject,
                    "company": company,
                    "raw_content": body or subject,
                    "salary_text": sal_text,
                    "salary_min_vnd": sal_min,
                    "salary_max_vnd": sal_max,
                    "district": district,
                    "job_type": classify_job_type(subject, body),
                    "url": f"https://www.vieclamtot.com/{list_id}.htm",
                    "source": "Việc Làm Tốt",
                    "posted_time": posted_time,
                    "image_url": image_url,
                    "phone": extract_phone(body),
                }
            )
        except Exception:
            continue

    log.info("Việc Làm Tốt (Chợ Tốt): thu được %d tin tuyển dụng.", len(results))
    return results


def crawl_vieclamdanang(limit: int = 40) -> List[Dict[str, Any]]:
    """Thu thập tin tuyển dụng từ trang chủ vieclamdanang.vn."""
    base_url = "https://vieclamdanang.vn/"
    results: List[Dict[str, Any]] = []
    seen_urls = set()

    try:
        resp = requests.get(base_url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        log.warning("Lỗi cào vieclamdanang.vn: %s", e)
        return []

    for a in soup.select('a[href*="/viec-lam/"]'):
        try:
            href = (a.get("href") or "").strip()
            if not href or not href.endswith(".html"):
                continue
            full_url = urljoin(base_url, href)
            if full_url in seen_urls:
                continue

            title = " ".join(a.get_text(" ", strip=True).split())
            if len(title) < 6:
                continue

            seen_urls.add(full_url)

            # Tìm card cha chứa thông tin công ty, lương và logo
            card = a.find_parent("div", class_=lambda c: c and any(k in c for k in ("col-", "job", "item", "box")))
            if card is None:
                card = a.find_parent("div")

            company = "Doanh nghiệp Đà Nẵng"
            salary_raw = "Thỏa thuận"
            image_url = None
            card_text = title

            if card:
                card_text = " | ".join(card.stripped_strings)
                parts = [p.strip() for p in card.stripped_strings if p.strip() and p.strip() != title]
                for p in parts:
                    p_low = p.lower()
                    if any(k in p_low for k in ("triệu", "thỏa thuận", "thương lượng", "usd", "tr")) and len(p) < 35:
                        salary_raw = p
                    elif company == "Doanh nghiệp Đà Nẵng" and not re.match(r"^\d{2}/\d{2}/\d{4}$", p) and len(p) > 3:
                        company = p

                img = card.select_one("img")
                if img:
                    src = img.get("data-src") or img.get("src")
                    if src and "logo" not in src.lower() or (src and "upload" in src.lower()):
                        image_url = urljoin(base_url, src)

            sal_min, sal_max, sal_text = parse_salary_range(salary_raw)
            district = normalize_district(f"{title} {card_text}") or "Đà Nẵng"

            results.append(
                {
                    "title": title,
                    "company": company,
                    "raw_content": card_text,
                    "salary_text": sal_text,
                    "salary_min_vnd": sal_min,
                    "salary_max_vnd": sal_max,
                    "district": district,
                    "job_type": classify_job_type(title, card_text),
                    "url": full_url,
                    "source": "Vieclamdanang",
                    "posted_time": datetime.now().isoformat(),
                    "image_url": image_url,
                    "phone": extract_phone(card_text),
                }
            )
            if len(results) >= limit:
                break
        except Exception:
            continue

    log.info("Vieclamdanang.vn: thu được %d tin tuyển dụng.", len(results))
    return results


def crawl_danang43_jobs(limit: int = 30) -> List[Dict[str, Any]]:
    """Thu thập tin tuyển dụng từ danang43.vn/viec-lam-da-nang."""
    url = "https://danang43.vn/viec-lam-da-nang"
    results: List[Dict[str, Any]] = []
    seen_urls = set()

    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        log.warning("Lỗi cào danang43.vn: %s", e)
        return []

    for art in soup.select("article"):
        try:
            a = art.select_one("h3 a") or art.select_one("h2 a") or art.select_one("a[href]")
            if not a:
                continue
            href = urljoin(url, (a.get("href") or "").strip())
            if not href or href in seen_urls:
                continue

            title = " ".join(a.get_text(" ", strip=True).split())
            if len(title) < 8:
                continue
            seen_urls.add(href)

            summary = " ".join(art.get_text(" ", strip=True).split())
            img = art.select_one("img")
            image_url = (img.get("data-src") or img.get("src")) if img else None
            if image_url:
                image_url = urljoin(url, image_url)

            # Tách tên công ty từ tiêu đề dạng "Tin tuyển dụng, việc làm <Công ty>"
            company = re.sub(
                r"^(?:tin\s+tuyển\s+dụng[,:\s]*|việc\s+làm[,:\s]*|tuyển\s+dụng[,:\s]*)+",
                "",
                title,
                flags=re.IGNORECASE,
            ).strip() or "Doanh nghiệp Đà Nẵng"

            sal_min, sal_max, sal_text = parse_salary_range(summary)
            district = normalize_district(summary) or "Đà Nẵng"

            results.append(
                {
                    "title": title,
                    "company": company[:80],
                    "raw_content": summary,
                    "salary_text": sal_text,
                    "salary_min_vnd": sal_min,
                    "salary_max_vnd": sal_max,
                    "district": district,
                    "job_type": classify_job_type(title, summary),
                    "url": href,
                    "source": "Danang43",
                    "posted_time": datetime.now().isoformat(),
                    "image_url": image_url,
                    "phone": extract_phone(summary),
                }
            )
            if len(results) >= limit:
                break
        except Exception:
            continue

    log.info("Danang43.vn: thu được %d tin tuyển dụng.", len(results))
    return results


def crawl_all_jobs() -> List[Dict[str, Any]]:
    """Thu thập việc làm Đà Nẵng từ tất cả các nguồn (lỗi nguồn nào bỏ qua nguồn đó)."""
    all_jobs: List[Dict[str, Any]] = []
    for fn in (crawl_chotot_jobs, crawl_vieclamdanang, crawl_danang43_jobs):
        try:
            all_jobs.extend(fn())
        except Exception as e:
            log.error("Lỗi crawler việc làm %s: %s", fn.__name__, e)
    log.info("Tổng cộng thu thập được %d tin việc làm Đà Nẵng.", len(all_jobs))
    return all_jobs


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    jobs = crawl_all_jobs()
    print(f"Total jobs: {len(jobs)}")
    for j in jobs[:5]:
        print(f" - [{j['source']}] {j['title']} | {j['company']} | {j['salary_text']} | {j['district']}")
