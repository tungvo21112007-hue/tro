# Đà Nẵng Rental Aggregator 🏠

Hệ thống tự động thu thập tin cho thuê phòng trọ, căn hộ tại Đà Nẵng từ Facebook Groups và Phongtro123, lọc tin rác và chuẩn hóa dữ liệu bằng Gemini AI (Gemini 2.5 Flash qua OpenRouter), lưu trữ vào SQLite và cung cấp Dashboard trực quan với Streamlit.

## 🚀 Tính năng chính

- **Đa nguồn thu thập**:
  - `fb_crawler.py`: Cào bài viết từ Facebook Groups bằng Playwright (cần đăng nhập 1 lần: `python fb_crawler.py --login`).
  - `web_crawler.py`: Cào tin từ `phongtro123.com` sử dụng Crawlee (`BeautifulSoupCrawler`).
- **AI lọc rác & chuẩn hóa** (`ai_filter.py`):
  - Nhận diện tin cho thuê thật vs. tin tìm phòng / pass đồ / quảng cáo.
  - Phát hiện giá ảo, tin câu tương tác, tin spam.
  - Tự động chuẩn hóa mức giá về VNĐ/tháng và map địa chỉ về 7 quận Đà Nẵng.
- **Tối ưu chi phí & Lập lịch tự động** (`pipeline.py`):
  - Kiểm tra trùng lặp URL trước khi gọi AI để tiết kiệm tối đa token.
  - Lập lịch quét tự động định kỳ mỗi 30 phút bằng `APScheduler`.
- **Giao diện tìm kiếm trực quan** (`app.py`):
  - Streamlit dashboard với bộ lọc đa tiêu chí: Quận (multiselect), khoảng giá, thời gian đăng, nguồn tin, từ khóa.
  - Nút kích hoạt quét tin mới thủ công và liên kết trực tiếp tới bài đăng gốc.

## 📁 Cấu trúc thư mục

```text
Danang-Rental-Aggregator/
├── requirements.txt   # Danh sách thư viện cần thiết
├── database.py        # Thao tác SQLite (bảng rentals)
├── fb_crawler.py      # Module cào Facebook Groups bằng Playwright
├── web_crawler.py     # Module cào Phongtro123 qua Crawlee
├── ai_filter.py       # Module lọc rác & chuẩn hóa bằng Gemini 2.5 Flash qua OpenRouter
├── pipeline.py        # Pipeline điều phối & scheduler
└── app.py             # Giao diện Streamlit Dashboard
```

## ⚙️ Cài đặt & Sử dụng

### 1. Cài đặt môi trường

```bash
git clone https://github.com/tungvo21112007-hue/tro.git
cd tro
pip install -r requirements.txt
```

### 2. Thiết lập biến môi trường

```bash
playwright install chromium
cp .env.example .env   # rồi điền OPENROUTER_API_KEY
export OPENROUTER_API_KEY="your_openrouter_api_key"
```

### 3. Vận hành

- **Chạy pipeline thu thập & lập lịch tự động**:
  ```bash
  python pipeline.py
  ```

- **Khởi động Web Dashboard**:
  ```bash
  streamlit run app.py
  ```
