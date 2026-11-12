"""
app.py – Streamlit dashboard tìm phòng trọ Đà Nẵng.
Chạy: streamlit run app.py
"""

import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

# ── Đồng bộ Streamlit Secrets sang os.environ (Hỗ trợ Streamlit Cloud) ─
try:
    if hasattr(st, "secrets"):
        for key in ["OPENROUTER_API_KEY", "OPENROUTER_MODEL", "FB_GROUP_URLS"]:
            if key in st.secrets and not os.environ.get(key):
                os.environ[key] = str(st.secrets[key])
        # Đồng bộ thêm tất cả string secrets khác nếu có
        for k, v in getattr(st.secrets, "_secrets", {}).items():
            if isinstance(v, str) and not os.environ.get(k):
                os.environ[k] = v
except Exception:
    pass

from database import get_rentals, init_db

# ── Page config ──────────────────────────────────────────────────────
st.set_page_config(
    page_title="Phòng trọ Đà Nẵng",
    page_icon="🏠",
    layout="wide",
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

SOURCE_OPTIONS = ["Facebook", "Phongtro123", "Chotot"]

TIME_PRESETS = {
    "24 giờ qua": timedelta(hours=24),
    "3 ngày qua": timedelta(days=3),
    "7 ngày qua": timedelta(days=7),
    "Tất cả": None,
}


# ── Helpers ──────────────────────────────────────────────────────────
def _format_price(value) -> str:
    if value is None or (isinstance(value, (int, float)) and value <= 0):
        return "Thỏa thuận"
    if isinstance(value, (int, float)):
        if value >= 1_000_000:
            return f"{value / 1_000_000:,.1f} triệu/th"
        return f"{value:,.0f}đ/th"
    return str(value)


def _format_time(iso_str) -> str:
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(str(iso_str))
        delta = datetime.now() - dt
        if delta < timedelta(hours=1):
            return f"{int(delta.total_seconds() // 60)} phút trước"
        if delta < timedelta(hours=24):
            return f"{int(delta.total_seconds() // 3600)} giờ trước"
        if delta < timedelta(days=7):
            return f"{delta.days} ngày trước"
        return dt.strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return str(iso_str)


def _run_pipeline_manual():
    """Gọi pipeline.run_pipeline() trong subprocess để không block Streamlit."""
    cwd = Path(__file__).resolve().parent
    subprocess.Popen(
        [sys.executable, "-c", "from pipeline import run_pipeline; run_pipeline()"],
        cwd=cwd,
        env=os.environ.copy(),
    )


# ══════════════════════════════════════════════════════════════════════
#  SIDEBAR — Bộ lọc
# ══════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.header("🔍 Bộ lọc tìm kiếm")

    # 1. Quận — Multiselect
    selected_districts = st.multiselect(
        "Quận / Huyện",
        options=DANANG_DISTRICTS,
        default=[],
        placeholder="Tất cả quận",
    )

    # 2. Khoảng giá — Slider
    price_range = st.slider(
        "Khoảng giá (VNĐ/tháng)",
        min_value=500_000,
        max_value=15_000_000,
        value=(500_000, 15_000_000),
        step=500_000,
        format="%d",
    )
    st.caption(
        f"{_format_price(price_range[0])}  →  {_format_price(price_range[1])}"
    )

    # 3. Thời gian đăng — Selectbox
    time_label = st.selectbox(
        "Thời gian đăng",
        options=list(TIME_PRESETS.keys()),
        index=3,
    )

    # 4. Nguồn tin — Checkbox
    st.markdown("**Nguồn tin**")
    source_checks = {}
    for src in SOURCE_OPTIONS:
        source_checks[src] = st.checkbox(src, value=True, key=f"src_{src}")

    selected_sources = [s for s, checked in source_checks.items() if checked]

    st.divider()

    # Tìm kiếm từ khóa
    keyword = st.text_input("🔎 Từ khóa", placeholder="VD: gần biển, full nội thất…")


# ══════════════════════════════════════════════════════════════════════
#  Xây dựng bộ lọc & truy vấn
# ══════════════════════════════════════════════════════════════════════
filters = {
    "min_price": price_range[0],
    "max_price": price_range[1],
    "limit": 200,
}

if selected_districts:
    filters["districts"] = selected_districts

if selected_sources and len(selected_sources) < len(SOURCE_OPTIONS):
    filters["sources"] = selected_sources

time_delta = TIME_PRESETS[time_label]
if time_delta is not None:
    filters["posted_after"] = (datetime.now() - time_delta).isoformat()

if keyword.strip():
    filters["keyword"] = keyword.strip()

rows = get_rentals(filters)


# ══════════════════════════════════════════════════════════════════════
#  KHU VỰC CHÍNH
# ══════════════════════════════════════════════════════════════════════
st.title("🏠 Phòng trọ Đà Nẵng")
st.caption("Tổng hợp tin cho thuê từ Facebook Groups, Phongtro123 & Chợ Tốt")

# ── Thanh điều khiển ─────────────────────────────────────────────────
col_count, col_btn = st.columns([3, 1])

with col_count:
    st.metric("Kết quả tìm thấy", f"{len(rows)} phòng")

with col_btn:
    if st.button("🔄 Quét tin mới ngay", use_container_width=True):
        _run_pipeline_manual()
        st.toast("Đang chạy pipeline quét tin mới… Tải lại trang sau 1–2 phút.", icon="⏳")

st.divider()

# ── Danh sách thẻ phòng trọ ──────────────────────────────────────────
if not rows:
    st.info(
        "Không tìm thấy phòng nào phù hợp. "
        "Thử mở rộng bộ lọc hoặc bấm **Quét tin mới ngay**."
    )
else:
    # Sắp xếp posted_time mới nhất lên đầu
    df = pd.DataFrame(rows)
    df["posted_time"] = pd.to_datetime(df["posted_time"], errors="coerce")
    df = df.sort_values("posted_time", ascending=False, na_position="last")

    for _, row in df.iterrows():
        price_display = _format_price(row.get("price_vnd"))
        district_display = row.get("district") or "—"
        room_type_display = row.get("room_type") or "—"
        time_display = _format_time(row.get("posted_time"))
        source_display = row.get("source") or "—"
        title = row.get("title") or "Không có tiêu đề"
        content = row.get("raw_content") or ""
        url = row.get("url") or ""

        # Cắt nội dung hiển thị tối đa 200 ký tự
        summary = content[:200] + ("…" if len(content) > 200 else "")

        with st.container(border=True):
            top_left, top_right = st.columns([4, 1])

            with top_left:
                st.markdown(f"### {title}")

            with top_right:
                st.markdown(
                    f"<p style='text-align:right; font-size:0.8rem; "
                    f"color:#888; margin:0;'>{source_display}</p>",
                    unsafe_allow_html=True,
                )

            # Thông tin chính
            c1, c2, c3, c4 = st.columns(4)
            c1.markdown(f"**💰 {price_display}**")
            c2.markdown(f"📍 {district_display}")
            c3.markdown(f"🏠 {room_type_display}")
            c4.markdown(f"🕐 {time_display}")

            # Tóm tắt nội dung
            if summary:
                st.markdown(
                    f"<p style='color:#555; font-size:0.9rem; margin-top:4px;'>"
                    f"{summary}</p>",
                    unsafe_allow_html=True,
                )

            # Nút mở link bài gốc
            if url:
                st.link_button("🔗 Xem bài gốc", url, use_container_width=False)
