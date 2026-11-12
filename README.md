# Đà Nẵng Rental Aggregator 🏠

Hệ thống tự động thu thập tin cho thuê phòng trọ Đà Nẵng từ Phongtro123, Chợ Tốt và Facebook Groups, lọc tin rác và chuẩn hóa dữ liệu **100% bằng Python & Regex thuần (0 tốn token AI)**, lưu trữ SQLite và hiển thị qua dashboard Streamlit dạng Card Layout hiện đại.

---

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
            │
      GitHub Actions: Tự động cào dữ liệu & sync rentals.db mỗi 2 tiếng
```

| File | Vai trò |
|---|---|
| `web_crawler.py` | `crawl_phongtro123()` đọc HTML và bóc tách trực tiếp ảnh, giá, quận, SĐT, diện tích $m^2$; `crawl_chotot()` gọi API JSON lấy trực tiếp giá VND, ảnh CDN và thông số kỹ thuật. |
| `fb_crawler.py` | `crawl_fb_groups()` dùng Playwright mở group, trích xuất bài đăng, lọc ảnh nội dung (bỏ qua avatar). |
| `ai_filter.py` | `filter_and_extract()` lọc rác, loại bỏ tin tìm phòng/pass đồ, bóc tách SĐT di động VN và diện tích $m^2$ bằng Regex thuần. |
| `database.py` | Quản lý bảng `rentals`, tự động migrate cột, truy vấn đa tiêu chí, và hàm `cleanup_old_rentals()` tự động xóa tin cũ > 14 ngày kèm `VACUUM` giữ DB luôn nhẹ (< 2MB). |
| `pipeline.py` | ETL điều phối crawler, lọc rác, lưu SQLite và dọn dẹp tin cũ định kỳ. |
| `app.py` | Dashboard Streamlit Card Layout: hiển thị ảnh đại diện, badge nguồn, giá to, diện tích, 1-click copy SĐT, bộ lọc giá nhanh, diện tích, và sắp xếp. |
| `.github/workflows/scrape.yml` | Workflow GitHub Actions tự động cào tin mới mỗi 2 tiếng và commit `rentals.db` lên repo. |

---

## 🤖 Tự động hóa với GitHub Actions

Hệ thống đã được cấu hình sẵn GitHub Actions (`.github/workflows/scrape.yml`) để cào dữ liệu tự động mỗi 2 tiếng:

1. **Cấu hình Secret cho Facebook (Khuyên dùng)**:
   - Vào repository trên GitHub: **Settings** $\rightarrow$ **Secrets and variables** $\rightarrow$ **Actions**.
   - Tại mục **Repository secrets**, nhấn **New repository secret**:
     - **Name**: `FB_COOKIES_JSON`
     - **Secret**: Sao chép toàn bộ nội dung file `fb_cookies.json` trên máy của bạn và dán vào.
   - *(Tùy chọn)* Tại mục **Repository variables**, có thể thêm `FB_GROUP_URLS` nếu muốn thay đổi danh sách URL nhóm Facebook cần quét.

2. **Chạy thủ công bất kỳ lúc nào**:
   - Vào tab **Actions** trên GitHub $\rightarrow$ Chọn workflow **Auto Scrape Rentals** $\rightarrow$ Bấm **Run workflow**.
   - Sau khi cào xong, bot sẽ tự động commit và push file `rentals.db` mới nhất lên nhánh `main`. Streamlit Cloud sẽ tự động nhận dữ liệu mới ngay lập tức!

---

## ⚙️ Cài đặt & Sử dụng Local

```bash
git clone https://github.com/tungvo21112007-hue/tro.git && cd tro
pip install -r requirements.txt
playwright install chromium
```

> [!NOTE]
> Dự án hoạt động **hoàn toàn độc lập không cần bất kỳ AI API Key nào**! Bạn có thể chạy ngay lập tức cả trên máy local lẫn Streamlit Cloud.

---

## 🔄 Chạy ứng dụng

- **Chạy pipeline thu thập & lọc rác ngay 1 lần**:
  ```bash
  python pipeline.py --once
  ```

- **Chạy pipeline với lịch định kỳ mỗi 30 phút trên local**:
  ```bash
  python pipeline.py
  ```

- **Mở giao diện Web Dashboard**:
  ```bash
  streamlit run app.py
  ```

---

## 👥 Quản lý Cookie Facebook

Facebook thường yêu cầu đăng nhập đối với một số nhóm kín hoặc nhóm công khai. Bạn có thể đăng nhập 1 lần trên máy local:
```bash
python fb_crawler.py --login
```
- Trình duyệt sẽ mở ra trang Facebook. Sau khi đăng nhập, hệ thống sẽ tự động phát hiện và lưu session vào `fb_profile/` đồng thời xuất toàn bộ cookies ra file `fb_cookies.json`.
- File `fb_cookies.json` và thư mục `fb_profile/` đã được chặn trong `.gitignore` để bảo mật tài khoản tuyệt đối.
