"""
job_crawler.py – Thu thập và bóc tách dữ liệu việc làm tại Đà Nẵng (0 tốn token AI).
Nguồn dữ liệu:
  1. Việc Làm Tốt / Chợ Tốt Việc Làm (JSON API gateway.chotot.com, region_v2=3017, cg=13010)
  2. Vieclamdanang.vn (HTML trang chủ + trang chi tiết song song)
  3. Danang43.vn (HTML chuyên mục việc làm + trang chi tiết song song)
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
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


STUDENT_POSITIVE_KWS = [
    "sinh viên", "part time", "part-time", "bán thời gian", "theo ca", "xoay ca",
    "ca sáng", "ca chiều", "ca tối", "linh hoạt", "thời vụ", "ctv", "cộng tác viên",
    "thực tập", "intern", "phục vụ", "pha chế", "barista", "thu ngân",
    "gia sư", "trợ giảng", "bán hàng", "làm thêm", "phụ quán", "order", "chạy bàn",
]

STUDENT_EXCLUDE_KWS = [
    "trưởng phòng", "giám đốc", "kế toán trưởng", "kỹ sư trưởng",
    "bằng c", "bằng d", "bằng e", "3 năm kinh nghiệm", "5 năm kinh nghiệm",
    "2 năm kinh nghiệm", "tuyển gấp thợ",
]


def is_student_job(
    title: str,
    content: str = "",
    work_type: Optional[str] = None,
    experience: Optional[str] = None,
) -> bool:
    """Xác định tin tuyển dụng có phù hợp cho sinh viên làm thêm / part-time / thực tập hay không."""
    combined = f"{title} {content} {work_type or ''} {experience or ''}".lower()
    has_explicit = any(kw in combined for kw in ("sinh viên", "part time", "part-time", "bán thời gian", "thực tập", "intern", "theo ca", "xoay ca"))
    if not has_explicit and any(ex in combined for ex in STUDENT_EXCLUDE_KWS):
        return False
    return any(kw in combined for kw in STUDENT_POSITIVE_KWS)


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
    Nếu không tìm thấy mẫu lương rõ ràng thì luôn trả về "Thỏa thuận" (không trả về đoạn văn dài).
    """
    if not text:
        return None, None, "Thỏa thuận"

    clean = " ".join(text.split())
    lower = clean.lower()

    if len(clean) <= 35 and any(w in lower for w in ("thỏa thuận", "thương lượng", "cạnh tranh")):
        return None, None, "Thỏa thuận"

    # Dạng khoảng: "10 - 15 triệu" hoặc "10-15tr"
    m_range = re.search(
        r"(\d+(?:[.,]\d+)?)\s*[-–~đến]+\s*(\d+(?:[.,]\d+)?)\s*(?:triệu|trieu|tr)\b",
        lower,
    )
    if m_range:
        v1 = int(float(m_range.group(1).replace(",", ".")) * 1_000_000)
        v2 = int(float(m_range.group(2).replace(",", ".")) * 1_000_000)
        s_min, s_max = min(v1, v2), max(v1, v2)
        fmt = f"{m_range.group(1)} - {m_range.group(2)} triệu/tháng"
        return s_min, s_max, fmt

    # Dạng một mức: "đến 10 triệu", "từ 8 triệu", "8.5 triệu", "12tr"
    m_single = re.search(
        r"(?:(từ|đến|tới)\s*)?(\d+(?:[.,]\d+)?)\s*(?:triệu|trieu|tr)\b",
        lower,
    )
    if m_single:
        v = int(float(m_single.group(2).replace(",", ".")) * 1_000_000)
        prefix = f"{m_single.group(1).capitalize()} " if m_single.group(1) else ""
        return v, v, f"{prefix}{m_single.group(2)} triệu/tháng"

    # Dạng lương giờ: "25k/giờ", "30.000đ/h"
    m_hour = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:k|nghìn|ngàn)\s*/\s*(?:h|giờ|buổi|ca)", lower)
    if m_hour:
        return None, None, m_hour.group(0)

    # Dạng số VND đầy đủ (vd "8.000.000 đ")
    m_full = re.search(r"(\d{1,2})[.,](\d{3})[.,]000", lower)
    if m_full:
        v = int(m_full.group(1) + m_full.group(2) + "000")
        return v, v, f"{v // 1_000_000} triệu/tháng"

    return None, None, "Thỏa thuận"


def _enrich_chotot_detail(job: Dict[str, Any], list_id: Any) -> Dict[str, Any]:
    """Lấy thêm địa chỉ, hình thức làm việc, kinh nghiệm, số lượng từ API chi tiết Chợ Tốt."""
    try:
        resp = requests.get(
            f"https://gateway.chotot.com/v1/public/ad-listing/{list_id}",
            headers=HEADERS,
            timeout=10,
        )
        if not resp.ok:
            return job
        data = resp.json()
        for p in data.get("parameters", []):
            label = (p.get("label") or "").lower()
            val = (p.get("value") or "").strip()
            if not val:
                continue
            if "địa chỉ" in label:
                job["address"] = val
            elif "loại công việc" in label:
                job["work_type"] = val
            elif "kinh nghiệm" in label:
                job["experience"] = val
            elif "số lượng" in label:
                job["quantity"] = val
            elif "tên công ty" in label and job.get("company") in ("Nhà tuyển dụng", "."):
                job["company"] = val
    except Exception:
        pass
    return job


def crawl_chotot_jobs(limit: int = 40) -> List[Dict[str, Any]]:
    """Thu thập tin tuyển dụng tại Đà Nẵng từ Chợ Tốt / Việc Làm Tốt JSON API (bao gồm lọc riêng cho sinh viên)."""
    endpoints = [
        f"https://gateway.chotot.com/v1/public/ad-listing?region_v2=3017&cg=13010&limit={limit}&st=s,k",
        "https://gateway.chotot.com/v1/public/ad-listing?region_v2=3017&cg=13010&q=sinh%20vi%C3%AAn&limit=25",
        "https://gateway.chotot.com/v1/public/ad-listing?region_v2=3017&cg=13010&q=b%C3%A1n%20th%E1%BB%9Di%20gian&limit=25",
        "https://gateway.chotot.com/v1/public/ad-listing?region_v2=3017&cg=13010&q=ph%E1%BB%A5c%20v%E1%BB%A5&limit=25",
    ]
    results: List[Tuple[Dict[str, Any], Any]] = []
    seen_ids = set()
    ads: List[Dict[str, Any]] = []
    for api_url in endpoints:
        try:
            resp = requests.get(api_url, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            for ad in resp.json().get("ads", []):
                lid = ad.get("list_id")
                if lid and lid not in seen_ids:
                    seen_ids.add(lid)
                    ads.append(ad)
        except Exception as e:
            log.warning("Lỗi gọi API Việc Làm Tốt (%s): %s", api_url, e)

    for ad in ads:
        try:
            list_id = ad.get("list_id")
            subject = (ad.get("subject") or "").strip()
            if not list_id or not subject:
                continue

            body = (ad.get("body") or "").strip()
            company = (ad.get("company_name") or ad.get("account_name") or "Nhà tuyển dụng").strip()
            if company == ".":
                company = "Nhà tuyển dụng"
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

            job = {
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
                "address": area_raw or None,
                "work_type": None,
                "experience": None,
                "deadline": None,
                "quantity": None,
            }
            results.append((job, list_id))
        except Exception:
            continue

    enriched: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_enrich_chotot_detail, j, lid) for j, lid in results]
        for fut in as_completed(futures):
            enriched.append(fut.result())

    log.info("Việc Làm Tốt (Chợ Tốt): thu được %d tin tuyển dụng.", len(enriched))
    return enriched


def _enrich_vieclamdanang_detail(job: Dict[str, Any]) -> Dict[str, Any]:
    """Lấy chi tiết quận, kinh nghiệm, số lượng, hình thức làm việc, mô tả từ vieclamdanang.vn."""
    try:
        resp = requests.get(job["url"], headers=HEADERS, timeout=10)
        if not resp.ok:
            return job
        soup = BeautifulSoup(resp.text, "html.parser")
        lines = [l.strip() for l in soup.get_text("\n").splitlines() if l.strip()]
        full_text = "\n".join(lines)

        def _after(label: str) -> Optional[str]:
            for i, line in enumerate(lines):
                if line.rstrip(":").lower() == label.lower() and i + 1 < len(lines):
                    return lines[i + 1]
            return None

        loc = _after("Địa điểm tuyển dụng")
        if loc:
            job["address"] = loc
            dist = normalize_district(loc)
            if dist:
                job["district"] = dist

        sal = _after("Mức lương")
        if sal:
            s_min, s_max, s_txt = parse_salary_range(sal)
            if s_txt != "Thỏa thuận":
                job["salary_min_vnd"], job["salary_max_vnd"], job["salary_text"] = s_min, s_max, s_txt

        job["experience"] = _after("Kinh nghiệm")
        job["work_type"] = _after("Hình thức làm việc")
        job["deadline"] = _after("Hạn nộp hồ sơ")
        job["quantity"] = _after("Số lượng cần tuyển")

        # Trích mô tả công việc sạch
        m_desc = re.search(r"Mô tả công việc\s*(.*?)(?:Quyền lợi|Yêu cầu hồ sơ|Thông tin liên hệ|$)", full_text, re.S)
        if m_desc:
            desc_clean = " ".join(m_desc.group(1).split())
            if len(desc_clean) > 20:
                job["raw_content"] = desc_clean[:1200]
                if not job.get("phone"):
                    job["phone"] = extract_phone(desc_clean)
    except Exception:
        pass
    return job


def crawl_vieclamdanang(limit: int = 40) -> List[Dict[str, Any]]:
    """Thu thập tin tuyển dụng từ trang chủ + trang chi tiết vieclamdanang.vn."""
    base_url = "https://vieclamdanang.vn/"
    raw_jobs: List[Dict[str, Any]] = []
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

            card = a.find_parent("div", class_=lambda c: c and any(k in c for k in ("col-", "job", "item", "box")))
            if card is None:
                card = a.find_parent("div")

            company = "Doanh nghiệp Đà Nẵng"
            salary_raw = "Thỏa thuận"
            deadline = None
            image_url = None
            card_text = title

            if card:
                card_text = " | ".join(card.stripped_strings)
                parts = [p.strip() for p in card.stripped_strings if p.strip() and p.strip() != title]
                for p in parts:
                    p_low = p.lower()
                    if any(k in p_low for k in ("triệu", "thỏa thuận", "thương lượng", "usd", "tr")) and len(p) < 35:
                        salary_raw = p
                    elif re.match(r"^\d{2}/\d{2}/\d{4}$", p):
                        deadline = p
                    elif company == "Doanh nghiệp Đà Nẵng" and len(p) > 3:
                        company = p

                img = card.select_one("img")
                if img:
                    src = img.get("data-src") or img.get("src")
                    if src and ("logo" not in src.lower() or "upload" in src.lower()):
                        image_url = urljoin(base_url, src)

            sal_min, sal_max, sal_text = parse_salary_range(salary_raw)
            district = normalize_district(f"{title} {card_text}") or "Đà Nẵng"

            raw_jobs.append(
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
                    "address": None,
                    "work_type": None,
                    "experience": None,
                    "deadline": deadline,
                    "quantity": None,
                }
            )
            if len(raw_jobs) >= limit:
                break
        except Exception:
            continue

    enriched: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_enrich_vieclamdanang_detail, j) for j in raw_jobs]
        for fut in as_completed(futures):
            enriched.append(fut.result())

    log.info("Vieclamdanang.vn: thu được %d tin tuyển dụng.", len(enriched))
    return enriched


def _enrich_danang43_detail(job: Dict[str, Any]) -> Dict[str, Any]:
    """Lấy địa chỉ, quận, mức lương, SĐT từ trang chi tiết danang43.vn."""
    try:
        resp = requests.get(job["url"], headers=HEADERS, timeout=10)
        if not resp.ok:
            return job
        soup = BeautifulSoup(resp.text, "html.parser")
        content_el = soup.select_one("div.content") or soup.select_one("article")
        if not content_el:
            return job

        text = " ".join(content_el.get_text(" ", strip=True).split())
        # Bỏ breadcrumb đầu
        text = re.sub(r"^Trang chủ\s*/[^/]+/[^.]+\.\s*", "", text)
        if len(text) > 40:
            job["raw_content"] = text[:1200]

        m_addr = re.search(r"Địa chỉ:\s*([^|]+?)(?:Quy mô:|Điện thoại:|Email:|Website:|$)", text)
        if m_addr:
            addr = m_addr.group(1).strip(" .,-")
            if len(addr) > 5:
                job["address"] = addr[:120]
                dist = normalize_district(addr)
                if dist:
                    job["district"] = dist

        if job["district"] == "Đà Nẵng":
            dist = normalize_district(text)
            if dist:
                job["district"] = dist

        s_min, s_max, s_txt = parse_salary_range(text)
        if s_txt != "Thỏa thuận":
            job["salary_min_vnd"], job["salary_max_vnd"], job["salary_text"] = s_min, s_max, s_txt

        phone = extract_phone(text)
        if phone:
            job["phone"] = phone
    except Exception:
        pass
    return job


def crawl_danang43_jobs(limit: int = 30) -> List[Dict[str, Any]]:
    """Thu thập tin tuyển dụng từ danang43.vn/viec-lam-da-nang + trang chi tiết."""
    url = "https://danang43.vn/viec-lam-da-nang"
    raw_jobs: List[Dict[str, Any]] = []
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
            summary = re.sub(r"\s*Xem chi tiết\s*$", "", summary).strip()
            img = art.select_one("img")
            image_url = (img.get("data-src") or img.get("src")) if img else None
            if image_url:
                image_url = urljoin(url, image_url)

            company = re.sub(
                r"^(?:tin\s+tuyển\s+dụng[,:\s]*|việc\s+làm[,:\s]*|tuyển\s+dụng[,:\s]*)+",
                "",
                title,
                flags=re.IGNORECASE,
            ).strip() or "Doanh nghiệp Đà Nẵng"

            sal_min, sal_max, sal_text = parse_salary_range(summary)
            district = normalize_district(summary) or "Đà Nẵng"

            raw_jobs.append(
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
                    "address": None,
                    "work_type": None,
                    "experience": None,
                    "deadline": None,
                    "quantity": None,
                }
            )
            if len(raw_jobs) >= limit:
                break
        except Exception:
            continue

    enriched: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_enrich_danang43_detail, j) for j in raw_jobs]
        for fut in as_completed(futures):
            enriched.append(fut.result())

    log.info("Danang43.vn: thu được %d tin tuyển dụng.", len(enriched))
    return enriched


def crawl_all_jobs() -> List[Dict[str, Any]]:
    """Thu thập việc làm Đà Nẵng từ tất cả các nguồn (lỗi nguồn nào bỏ qua nguồn đó)."""
    all_jobs: List[Dict[str, Any]] = []
    for fn in (crawl_chotot_jobs, crawl_vieclamdanang, crawl_danang43_jobs):
        try:
            all_jobs.extend(fn())
        except Exception as e:
            log.error("Lỗi crawler việc làm %s: %s", fn.__name__, e)

    for job in all_jobs:
        job["is_student"] = 1 if is_student_job(
            job.get("title", ""),
            job.get("raw_content", ""),
            job.get("work_type"),
            job.get("experience"),
        ) else 0

    log.info("Tổng cộng thu thập được %d tin việc làm Đà Nẵng.", len(all_jobs))
    return all_jobs


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    jobs = crawl_all_jobs()
    print(f"Total jobs: {len(jobs)}")
    for j in jobs[:5]:
        print(
            f" - [{j['source']}] {j['title']} | {j['company']} | "
            f"{j['salary_text']} | {j['district']} | {j.get('address')} | {j.get('work_type')}"
        )
