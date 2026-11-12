"""
app.py – Streamlit dashboard tìm phòng trọ Đà Nẵng (Kiến trúc 0-token).
Giao diện Card Layout hiện đại, bóc tách ảnh đại diện, SĐT, diện tích m² và bộ lọc đa chiều.
Chạy: streamlit run app.py
"""

import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st

# ── Đồng bộ Streamlit Secrets sang os.environ (Hỗ trợ Streamlit Cloud) ─
try:
    if hasattr(st, "secrets"):
        for key in ["FB_GROUP_URLS", "FB_COOKIES_JSON"]:
            if key in st.secrets and not os.environ.get(key):
                os.environ[key] = str(st.secrets[key])
        for k, v in getattr(st.secrets, "_secrets", {}).items():
            if isinstance(v, str) and not os.environ.get(k):
                os.environ[k] = v
except Exception:
    pass

from database import get_rentals, init_db

# ── Page config ──────────────────────────────────────────────────────
st.set_page_config(
    page_title="Phòng trọ Đà Nẵng – Danang Rental Aggregator",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_db()

DANANG_DISTRICTS = [
    "Hải Châu",
    "Thanh Khê",
    "Sơn Trà",
    "Ngũ Hành Sơn",
    "Liên Chiểu",
    "Cẩm Lệ",
    "Hòa Vang",
]

ROOM_TYPES = [
    "Tất cả",
    "Phòng trọ",
    "Chung cư mini / Căn hộ",
    "Nhà nguyên căn",
    "Ở ghép",
]

SOURCE_OPTIONS = ["Facebook", "Phongtro123", "Chotot"]

TIME_PRESETS = {
    "24 giờ qua": timedelta(hours=24),
    "3 ngày qua": timedelta(days=3),
    "7 ngày qua": timedelta(days=7),
    "Tất cả": None,
}

PRICE_PRESETS = {
    "Tất cả": (500_000, 15_000_000),
    "< 2 triệu": (500_000, 2_000_000),
    "2 – 4 triệu": (2_000_000, 4_000_000),
    "4 – 7 triệu": (4_000_000, 7_000_000),
    "> 7 triệu": (7_000_000, 15_000_000),
}

SORT_OPTIONS = {
    "🕒 Mới nhất": "newest",
    "💵 Giá: Thấp → Cao": "price_asc",
    "💰 Giá: Cao → Thấp": "price_desc",
    "📐 Diện tích: Lớn → Nhỏ": "area_desc",
}

PLACEHOLDER_IMG = "https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?auto=format&fit=crop&w=500&q=80"


# ── CSS Styling ──────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    /* Card UI styling */
    .rental-card {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 16px;
        margin-bottom: 16px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
        transition: transform 0.15s ease, box-shadow 0.15s ease;
    }
    .rental-card:hover {
        border-color: #cbd5e1;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
    }
    .badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 6px;
        font-size: 0.75rem;
        font-weight: 600;
        margin-right: 6px;
        margin-bottom: 4px;
    }
    .badge-fb { background-color: #e0f2fe; color: #0369a1; }
    .badge-pt { background-color: #fef3c7; color: #b45309; }
    .badge-ct { background-color: #dcfce7; color: #15803d; }
    .badge-district { background-color: #f1f5f9; color: #334155; }
    .badge-room { background-color: #f3e8ff; color: #7e22ce; }
    .price-tag {
        font-size: 1.25rem;
        font-weight: 800;
        color: #0284c7;
    }
    .area-tag {
        font-size: 0.95rem;
        font-weight: 600;
        color: #475569;
        margin-left: 8px;
    }
    .phone-box {
        background-color: #f8fafc;
        border: 1px dashed #cbd5e1;
        border-radius: 8px;
        padding: 4px 10px;
        display: inline-block;
        font-weight: 700;
        color: #0f172a;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ── Helpers ──────────────────────────────────────────────────────────
def _format_price(value) -> str:
    if value is None or (isinstance(value, (int, float)) and value <= 0):
        return "Giá thỏa thuận"
    if isinstance(value, (int, float)):
        if value >= 1_000_000:
            val_tr = value / 1_000_000
            return f"{val_tr:.1f} triệu/th" if val_tr % 1 != 0 else f"{int(val_tr)} triệu/th"
        return f"{value:,.0f}đ/th"
    return str(value)


def _format_time(iso_str) -> str:
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(str(iso_str))
        delta = datetime.now() - dt
        if delta < timedelta(hours=1):
            return f"{max(1, int(delta.total_seconds() // 60))} phút trước"
        if delta < timedelta(hours=24):
            return f"{int(delta.total_seconds() // 3600)} giờ trước"
        if delta < timedelta(days=7):
            return f"{delta.days} ngày trước"
        return dt.strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return str(iso_str)


def _run_pipeline_manual():
    """
    Gọi pipeline.py --once trong subprocess không block Streamlit.
    Sử dụng sys.executable để luôn dùng đúng Python của virtualenv.
    """
    cwd = Path(__file__).resolve().parent
    subprocess.Popen(
        [sys.executable, "pipeline.py", "--once"],
        cwd=cwd,
        env=os.environ.copy(),
        stdout=None,
        stderr=None,
    )


# ══════════════════════════════════════════════════════════════════════
#  SIDEBAR — BỘ LỌC TÌM KIẾM
# ══════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.title("🔍 Bộ lọc phòng trọ")

    # 1. Quận / Huyện
    selected_districts = st.multiselect(
        "📍 Quận / Huyện",
        options=DANANG_DISTRICTS,
        default=[],
        placeholder="Tất cả quận",
    )

    # 2. Loại phòng
    selected_room_type = st.selectbox(
        "🏠 Loại phòng",
        options=ROOM_TYPES,
        index=0,
    )

    st.markdown("---")

    # 3. Khoảng giá (Nút chọn nhanh + Slider đồng bộ)
    st.markdown("**💰 Khoảng giá (VNĐ/tháng)**")

    # Quản lý session state cho khoảng giá
    if "price_preset" not in st.session_state:
        st.session_state["price_preset"] = "Tất cả"

    preset_choice = st.radio(
        "Mức giá nhanh",
        options=list(PRICE_PRESETS.keys()),
        horizontal=True,
        label_visibility="collapsed",
        key="radio_price_preset",
    )

    preset_min, preset_max = PRICE_PRESETS[preset_choice]

    price_range = st.slider(
        "Tùy chỉnh khoảng giá",
        min_value=500_000,
        max_value=15_000_000,
        value=(preset_min, preset_max),
        step=100_000,
        format="%d đ",
    )
    st.caption(f"Khoảng giá: **{_format_price(price_range[0])}**  →  **{_format_price(price_range[1])}**")

    st.markdown("---")

    # 4. Diện tích (m²)
    st.markdown("**📐 Diện tích (m²)**")
    area_range = st.slider(
        "Khoảng diện tích",
        min_value=0,
        max_value=100,
        value=(0, 100),
        step=5,
        format="%d m²",
        label_visibility="collapsed",
    )
    include_null_area = st.checkbox(
        "Bao gồm tin chưa ghi diện tích",
        value=True,
        help="Nhiều chủ phòng không ghi diện tích trong tin đăng nhưng vẫn là tin hợp lệ.",
    )

    st.markdown("---")

    # 5. Sắp xếp
    sort_choice = st.selectbox(
        "🔃 Sắp xếp theo",
        options=list(SORT_OPTIONS.keys()),
        index=0,
    )

    # 6. Thời gian đăng
    time_label = st.selectbox(
        "⏰ Thời gian đăng",
        options=list(TIME_PRESETS.keys()),
        index=3,
    )

    # 7. Nguồn tin
    st.markdown("**🌐 Nguồn tin**")
    source_checks = {}
    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        source_checks["Facebook"] = st.checkbox("Facebook", value=True)
    with col_s2:
        source_checks["Phongtro123"] = st.checkbox("Phongtro123", value=True)
    with col_s3:
        source_checks["Chotot"] = st.checkbox("Chợ Tốt", value=True)

    selected_sources = [s for s, checked in source_checks.items() if checked]

    # 8. Tiêu chí bổ sung
    st.markdown("**⭐ Tiêu chí bổ sung**")
    has_phone_only = st.checkbox("Chỉ hiện tin có Số điện thoại", value=False)
    has_image_only = st.checkbox("Chỉ hiện tin có Hình ảnh", value=False)

    # 9. Tìm kiếm từ khóa
    keyword = st.text_input("🔎 Tìm kiếm từ khóa", placeholder="VD: kiệt, full nội thất, gác lửng…")


# ══════════════════════════════════════════════════════════════════════
#  TRUY VẤN DỮ LIỆU
# ══════════════════════════════════════════════════════════════════════
filters: Dict[str, Any] = {
    "min_price": price_range[0],
    "max_price": price_range[1],
    "min_area": area_range[0],
    "max_area": area_range[1],
    "include_null_area": include_null_area,
    "has_phone": has_phone_only,
    "has_image": has_image_only,
    "sort_by": SORT_OPTIONS[sort_choice],
    "limit": 200,
}

if selected_districts:
    filters["districts"] = selected_districts

if selected_room_type and selected_room_type != "Tất cả":
    filters["room_type"] = selected_room_type

if selected_sources and len(selected_sources) < len(SOURCE_OPTIONS):
    filters["sources"] = selected_sources

time_delta = TIME_PRESETS[time_label]
if time_delta is not None:
    filters["posted_after"] = (datetime.now() - time_delta).isoformat()

if keyword.strip():
    filters["keyword"] = keyword.strip()

rows = get_rentals(filters)


# ══════════════════════════════════════════════════════════════════════
#  KHU VỰC CHÍNH (MAIN DASHBOARD)
# ══════════════════════════════════════════════════════════════════════
col_title, col_action = st.columns([3, 1])

with col_title:
    st.title("🏠 Phòng Trọ Đà Nẵng")
    st.caption("Cập nhật tự động từ Facebook Groups, Phongtro123 & Chợ Tốt • Lọc sạch 0 tốn token AI")

with col_action:
    if st.button("🔄 Quét tin mới ngay", width="stretch", type="primary"):
        _run_pipeline_manual()
        st.toast("Đang tiến hành cào tin mới từ các nguồn…", icon="⏳")
        st.info("⏳ **Đang cào dữ liệu trong nền!**\n\nHãy theo dõi tab **Manage app** (Logs) hoặc đợi 1–2 phút rồi nhấn `F5` để tải lại dữ liệu mới nhất.")

# Thanh thống kê
fb_count = sum(1 for r in rows if (r.get("source") or "").lower() == "facebook")
pt_count = sum(1 for r in rows if "phongtro" in (r.get("source") or "").lower())
ct_count = sum(1 for r in rows if "chotot" in (r.get("source") or "").lower())

col_m1, col_m2, col_m3 = st.columns(3)
with col_m1:
    st.metric("Kết quả phù hợp", f"{len(rows)} phòng")
    st.caption(f"🔵 Facebook: **{fb_count}** | 🟠 Phongtro123: **{pt_count}** | 🟢 Chợ Tốt: **{ct_count}**")
with col_m2:
    with_phone_cnt = sum(1 for r in rows if r.get("phone"))
    st.metric("Tin có số điện thoại", f"{with_phone_cnt} ({int(with_phone_cnt / max(1, len(rows)) * 100)}%)")
with col_m3:
    with_img_cnt = sum(1 for r in rows if r.get("image_url"))
    st.metric("Tin có hình ảnh", f"{with_img_cnt} ({int(with_img_cnt / max(1, len(rows)) * 100)}%)")

st.markdown("---")

# ── Hiển thị danh sách thẻ phòng trọ ──────────────────────────────────
if not rows:
    st.info("💡 Không tìm thấy phòng trọ nào phù hợp với bộ lọc hiện tại. Hãy thử nới rộng khoảng giá, diện tích hoặc bỏ bớt tiêu chí.")
else:
    for item in rows:
        title = item.get("title") or "Cho thuê phòng trọ Đà Nẵng"
        price_str = _format_price(item.get("price_vnd"))
        district_str = item.get("district") or "Đà Nẵng"
        room_type_str = item.get("room_type") or "Phòng trọ"
        time_str = _format_time(item.get("posted_time"))
        source = item.get("source") or "Khác"
        url = item.get("url") or "#"
        phone = item.get("phone")
        area_m2 = item.get("area_m2")
        image_url = item.get("image_url") or PLACEHOLDER_IMG
        content = item.get("raw_content") or ""

        # Xác định class badge nguồn
        source_badge_class = "badge-fb"
        if "phongtro" in source.lower():
            source_badge_class = "badge-pt"
        elif "chotot" in source.lower():
            source_badge_class = "badge-ct"

        # Hiển thị dạng Card 2 cột
        with st.container(border=True):
            col_img, col_info = st.columns([1, 2.5], gap="medium")

            # Cột trái: Ảnh đại diện
            with col_img:
                st.image(image_url, width="stretch")

            # Cột phải: Thông tin chi tiết
            with col_info:
                # Dòng Badges
                badge_html = f"""
                <div>
                    <span class="badge {source_badge_class}">🌐 {source}</span>
                    <span class="badge badge-district">📍 {district_str}</span>
                    <span class="badge badge-room">🏠 {room_type_str}</span>
                    <span class="badge badge-district">⏰ {time_str}</span>
                </div>
                """
                st.markdown(badge_html, unsafe_allow_html=True)

                # Tiêu đề
                st.markdown(f"#### [{title}]({url})")

                # Giá tiền & Diện tích
                area_display = f"• 📐 {area_m2} m²" if area_m2 else "• 📐 Chưa rõ diện tích"
                st.markdown(
                    f"<p><span class='price-tag'>{price_str}</span> <span class='area-tag'>{area_display}</span></p>",
                    unsafe_allow_html=True,
                )

                # Số điện thoại & Thao tác
                c_phone, c_btn = st.columns([1.5, 1])
                with c_phone:
                    if phone:
                        st.markdown(f"**📞 SĐT liên hệ:** ` {phone} `")
                    else:
                        st.caption("📞 SĐT: *Xem trong bài đăng gốc*")

                with c_btn:
                    st.link_button("🔗 Xem bài gốc", url, width="stretch")

                # Nội dung rút gọn có thể mở rộng
                if content:
                    summary = content[:180] + ("…" if len(content) > 180 else "")
                    with st.expander("📄 Xem tóm tắt nội dung bài viết"):
                        st.write(content)
                    st.caption(summary)
