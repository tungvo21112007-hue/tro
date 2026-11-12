# Đà Nẵng Rental Aggregator 🏠

Hệ thống tự động thu thập tin cho thuê phòng trọ Đà Nẵng từ Phongtro123, Chợ Tốt và Facebook Groups, lọc tin rác và chuẩn hóa dữ liệu **100% bằng Python & Regex thuần (0 tốn token AI)**, lưu trữ SQLite và hiển thị qua dashboard Streamlit.

## 🚀 Kiến trúc (100% Zero-Token)

```
web_crawler.py  (Phongtro123: requests+BS4 | Chợ Tốt: API JSON) ─┐
fb_crawler.py   (Facebook Groups: Playwright)                    ─┴► pipeline.py
      url_exists()? ─ đã có ─► bỏ qua (không quét lại)
            │ chưa có
            ▼
      ai_filter.py (Regex & Rule-based Heuristic 100% Python)
            │ is_valid_rental == True và is_spam == False
            ▼
      database.py (SQLite rentals.db) ◄── app.py (Streamlit Dashboard)
      APScheduler: chạy tự động định kỳ mỗi 30 phút
```

| File | Vai trò |
|---|---|
| `web_crawler.py` | `crawl_phongtro123()` đọc HTML và bóc tách trực tiếp giá, quận; `crawl_chotot()` gọi `gateway.chotot.com/v1/public/ad-listing` lấy trực tiếp giá VND và tên quận từ JSON. |
| `fb_crawler.py` | `crawl_fb_groups()` dùng Playwright mở group, cuộn trang, lấy nội dung + link bài. |
| `ai_filter.py` | `filter_and_extract()` lọc rác, loại bỏ tin tìm phòng/pass đồ, chuẩn hóa quận và phân loại phòng bằng Regex thuần. |
| `database.py` | Bảng `rentals`, `insert_rental()` (`INSERT OR IGNORE`), `url_exists()`, `get_rentals(filters)`. |
| `pipeline.py` | ETL điều phối crawler, lọc rác và lưu SQLite + APScheduler 30 phút/lần. |
| `app.py` | Dashboard Streamlit: lọc Quận, Giá, Thời gian, Nguồn, Từ khóa; nút "Quét tin mới ngay" chạy trực tiếp không cần API key. |

## ⚙️ Cài đặt & Sử dụng

```bash
git clone https://github.com/tungvo21112007-hue/tro.git && cd tro
pip install -r requirements.txt
playwright install chromium
```

> [!NOTE]
> Dự án hoạt động **hoàn toàn độc lập không cần bất kỳ API Key nào**! Bạn có thể chạy ngay lập tức cả trên máy local lẫn Streamlit Cloud.

## 🔄 Chạy ứng dụng

- **Chạy pipeline thu thập & lọc rác ngay 1 lần**:
  ```bash
  python pipeline.py --once
  ```

- **Chạy pipeline với lịch định kỳ mỗi 30 phút**:
  ```bash
  python pipeline.py
  ```

- **Mở giao diện Web Dashboard**:
  ```bash
  streamlit run app.py
  ```

## 👥 Facebook Crawler (Hỗ trợ Cookie & Cloud)

Facebook thường yêu cầu đăng nhập đối với một số nhóm. Bạn có thể đăng nhập 1 lần trên máy local:
```bash
python fb_crawler.py --login
```
- Trình duyệt sẽ mở ra trang Facebook. Sau khi đăng nhập, hệ thống sẽ tự động phát hiện và lưu session vào `fb_profile/` đồng thời xuất toàn bộ cookies ra file `fb_cookies.json`.
- **Triển khai trên Streamlit Cloud**: Sao chép nội dung file `fb_cookies.json` và dán vào Streamlit Secrets:
  ```toml
  FB_COOKIES_JSON = '''[ ... ]'''
  ```
- Nếu chưa đăng nhập hoặc trên môi trường Cloud không có browser, crawler Facebook sẽ tự động bỏ qua an toàn mà không làm ảnh hưởng đến nguồn Phongtro123 và Chợ Tốt.
