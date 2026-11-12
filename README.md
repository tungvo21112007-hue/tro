# Đà Nẵng Rental Aggregator 🏠

Tự động thu thập tin cho thuê phòng trọ Đà Nẵng từ Phongtro123, Chợ Tốt và Facebook Groups, lọc tin rác bằng AI (OpenRouter), lưu SQLite và xem qua dashboard Streamlit. Toàn bộ mã nguồn mở, không dùng dịch vụ cào trả phí.

## Kiến trúc

```
web_crawler.py  (Phongtro123: requests+BS4 | Chợ Tốt: API JSON) ─┐
fb_crawler.py   (Facebook Groups: Playwright)                    ─┴► pipeline.py
      url_exists()? ─ đã có ─► bỏ qua (không tốn token)
            │ chưa có
            ▼
      ai_filter.py (OpenRouter, Pydantic schema)
            │ is_valid_rental == True và is_spam == False
            ▼
      database.py (SQLite rentals.db) ◄── app.py (Streamlit)
      APScheduler: chạy lại mỗi 30 phút
```

| File | Vai trò |
|---|---|
| `web_crawler.py` | `crawl_phongtro123()` đọc HTML `phongtro123.com/tinh-thanh/da-nang`; `crawl_chotot()` gọi `gateway.chotot.com/v1/public/ad-listing` (danh mục phòng trọ, Đà Nẵng). Thời gian đăng lấy chính xác từ trang/API. |
| `fb_crawler.py` | `crawl_fb_groups()` dùng Playwright mở group, cuộn trang, lấy nội dung + link bài. |
| `ai_filter.py` | `analyze_rental()` gọi OpenRouter, trả `is_valid_rental`, `is_spam`, `price_vnd`, `district`, `room_type`. |
| `database.py` | Bảng `rentals`, `insert_rental()` (`INSERT OR IGNORE`), `url_exists()`, `get_rentals(filters)`. |
| `pipeline.py` | ETL + APScheduler 30 phút/lần. |
| `app.py` | Dashboard: lọc Quận, Giá, Thời gian, Nguồn, Từ khóa; nút "Quét tin mới ngay". |

## Cài đặt

```bash
git clone https://github.com/tungvo21112007-hue/tro.git && cd tro
pip install -r requirements.txt
playwright install chromium

cp .env.example .env        # điền OPENROUTER_API_KEY (https://openrouter.ai/keys)
set -a; source .env; set +a # nạp biến môi trường vào shell hiện tại
```

Biến môi trường:

| Biến | Ý nghĩa |
|---|---|
| `OPENROUTER_API_KEY` | Bắt buộc. |
| `OPENROUTER_MODEL` | Mặc định `google/gemini-2.5-flash`. |
| `FB_GROUP_URLS` | Tùy chọn, URL các Facebook Group, ngăn cách bằng dấu phẩy. |

## Facebook (đọc kỹ)

Facebook thường chặn người chưa đăng nhập, kể cả với group công khai. Đăng nhập một lần, session lưu ở `fb_profile/` (đã `.gitignore`):

```bash
python fb_crawler.py --login   # đăng nhập tay rồi nhấn Enter
python fb_crawler.py --show    # chạy thử có hiện trình duyệt
```

Chưa đăng nhập thì crawler cảnh báo và bỏ qua group; Phongtro123 và Chợ Tốt vẫn chạy bình thường. Dùng tài khoản phụ, vì tự động hóa có thể vi phạm điều khoản Facebook. Thời gian đăng của bài Facebook hiện là giờ lúc cào.

## Chạy

```bash
python web_crawler.py     # thử riêng crawler web (không cần API key)
python pipeline.py        # chạy ngay 1 lần, sau đó lặp mỗi 30 phút
streamlit run app.py      # mở dashboard
```

## Lưu ý

- Selector Phongtro123 và tham số Chợ Tốt (`cg=1050`, `region_v2=3017`) có thể đổi theo thời gian; `python web_crawler.py` giúp kiểm tra nhanh.
- Tin có `price_vnd` rỗng ("thỏa thuận") sẽ bị loại khi lọc theo khoảng giá trong dashboard.
