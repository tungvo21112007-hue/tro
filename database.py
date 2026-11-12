import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).resolve().parent / "rentals.db"


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Tạo hoặc lấy kết nối tới SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    """Tạo bảng rentals và tự động migrate các cột mới nếu cần."""
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS rentals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        raw_content TEXT,
        price_vnd INTEGER,
        district TEXT,
        room_type TEXT,
        url TEXT UNIQUE,
        source TEXT,
        posted_time DATETIME,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        image_url TEXT,
        phone TEXT,
        area_m2 REAL
    );
    """
    with get_connection(db_path) as conn:
        conn.execute(create_table_sql)

        # Kiểm tra và tự động migration thêm cột nếu chưa có (bảo vệ db cũ)
        cursor = conn.execute("PRAGMA table_info(rentals);")
        existing_cols = {row["name"] for row in cursor.fetchall()}

        new_cols = [
            ("image_url", "TEXT"),
            ("phone", "TEXT"),
            ("area_m2", "REAL"),
        ]
        for col_name, col_type in new_cols:
            if col_name not in existing_cols:
                conn.execute(f"ALTER TABLE rentals ADD COLUMN {col_name} {col_type};")

        conn.commit()


def insert_rental(data: Dict[str, Any], db_path: Path = DB_PATH) -> bool:
    """
    Thêm bản ghi mới vào bảng rentals.
    Tự động bỏ qua nếu URL đã tồn tại trong database (INSERT OR IGNORE).
    """
    sql = """
    INSERT OR IGNORE INTO rentals (
        title, raw_content, price_vnd, district, room_type,
        url, source, posted_time, created_at,
        image_url, phone, area_m2
    ) VALUES (
        :title, :raw_content, :price_vnd, :district, :room_type,
        :url, :source, :posted_time, :created_at,
        :image_url, :phone, :area_m2
    );
    """
    payload = {
        "title": data.get("title"),
        "raw_content": data.get("raw_content"),
        "price_vnd": data.get("price_vnd"),
        "district": data.get("district"),
        "room_type": data.get("room_type"),
        "url": data.get("url"),
        "source": data.get("source"),
        "posted_time": data.get("posted_time"),
        "created_at": data.get("created_at") or datetime.now().isoformat(),
        "image_url": data.get("image_url"),
        "phone": data.get("phone"),
        "area_m2": data.get("area_m2"),
    }

    with get_connection(db_path) as conn:
        cursor = conn.execute(sql, payload)
        conn.commit()
        return cursor.rowcount > 0


def url_exists(url: str, db_path: Path = DB_PATH) -> bool:
    """Kiểm tra nhanh xem URL đã tồn tại trong bảng rentals chưa."""
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT 1 FROM rentals WHERE url = ? LIMIT 1", (url,)).fetchone()
        return row is not None


def get_rentals(
    filters: Optional[Dict[str, Any]] = None,
    db_path: Path = DB_PATH,
) -> List[Dict[str, Any]]:
    """
    Truy vấn dữ liệu từ bảng rentals dựa theo bộ lọc `filters`.

    Các trường hỗ trợ trong `filters`:
        - districts (list) / district (str): Lọc theo quận/huyện
        - room_type (str): Lọc theo loại phòng
        - sources (list) / source (str): Lọc theo nguồn tin
        - min_price (int), max_price (int): Khoảng giá (VND)
        - min_area (float), max_area (float): Khoảng diện tích (m²)
        - include_null_area (bool): Cho phép lấy cả tin chưa rõ diện tích (mặc định True)
        - has_phone (bool): Chỉ lấy tin có SĐT
        - has_image (bool): Chỉ lấy tin có ảnh xem trước
        - keyword (str): Tìm kiếm từ khóa
        - sort_by (str): "newest", "price_asc", "price_desc", "area_desc"
        - limit (int), offset (int): Phân trang
    """
    filters = filters or {}
    conditions: List[str] = []
    params: List[Any] = []

    # 1. Lọc quận
    districts = filters.get("districts")
    district = filters.get("district")
    if districts and isinstance(districts, list) and len(districts) > 0:
        placeholders = ", ".join("?" for _ in districts)
        conditions.append(f"district IN ({placeholders})")
        params.extend(districts)
    elif district and district.lower() != "tất cả":
        conditions.append("district = ?")
        params.append(district)

    # 2. Lọc loại phòng
    room_type = filters.get("room_type")
    if room_type and room_type.lower() != "tất cả":
        conditions.append("room_type = ?")
        params.append(room_type)

    # 3. Lọc nguồn tin
    sources = filters.get("sources")
    source = filters.get("source")
    if sources and isinstance(sources, list) and len(sources) > 0:
        placeholders = ", ".join("?" for _ in sources)
        conditions.append(f"source IN ({placeholders})")
        params.extend(sources)
    elif source and source.lower() != "tất cả":
        conditions.append("source = ?")
        params.append(source)

    # 4. Lọc khoảng giá
    min_price = filters.get("min_price") if filters.get("min_price") is not None else filters.get("min_price_vnd")
    if min_price is not None:
        conditions.append("price_vnd >= ?")
        params.append(int(min_price))

    max_price = filters.get("max_price") if filters.get("max_price") is not None else filters.get("max_price_vnd")
    if max_price is not None:
        conditions.append("price_vnd <= ?")
        params.append(int(max_price))

    # 5. Lọc diện tích
    min_area = filters.get("min_area")
    max_area = filters.get("max_area")
    include_null_area = filters.get("include_null_area", True)
    if min_area is not None and max_area is not None:
        if include_null_area:
            conditions.append("((area_m2 >= ? AND area_m2 <= ?) OR area_m2 IS NULL)")
            params.extend([float(min_area), float(max_area)])
        else:
            conditions.append("(area_m2 >= ? AND area_m2 <= ?)")
            params.extend([float(min_area), float(max_area)])

    # 6. Lọc tùy chọn (has_phone, has_image)
    if filters.get("has_phone"):
        conditions.append("(phone IS NOT NULL AND length(trim(phone)) >= 9)")

    if filters.get("has_image"):
        conditions.append("(image_url IS NOT NULL AND length(trim(image_url)) > 5)")

    # 7. Lọc từ khóa
    keyword = filters.get("keyword") or filters.get("q")
    if keyword:
        conditions.append("(title LIKE ? OR raw_content LIKE ?)")
        search_term = f"%{keyword}%"
        params.extend([search_term, search_term])

    # 8. Lọc thời gian đăng
    posted_after = filters.get("posted_after")
    if posted_after:
        conditions.append("posted_time >= ?")
        params.append(str(posted_after))

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    # Sắp xếp
    sort_by = filters.get("sort_by", "newest")
    if sort_by == "price_asc":
        order_clause = "ORDER BY CASE WHEN price_vnd IS NULL THEN 1 ELSE 0 END, price_vnd ASC, posted_time DESC"
    elif sort_by == "price_desc":
        order_clause = "ORDER BY CASE WHEN price_vnd IS NULL THEN 1 ELSE 0 END, price_vnd DESC, posted_time DESC"
    elif sort_by == "area_desc":
        order_clause = "ORDER BY CASE WHEN area_m2 IS NULL THEN 1 ELSE 0 END, area_m2 DESC, posted_time DESC"
    else:  # "newest"
        order_clause = "ORDER BY posted_time DESC, created_at DESC"

    limit = int(filters.get("limit", 200))
    offset = int(filters.get("offset", 0))

    query = f"""
    SELECT * FROM rentals
    {where_clause}
    {order_clause}
    LIMIT ? OFFSET ?;
    """
    params.extend([limit, offset])

    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def cleanup_old_rentals(days: int = 14, db_path: Path = DB_PATH) -> int:
    """
    Tự động dọn dẹp các tin đăng cũ hơn `days` ngày để giữ file SQLite luôn gọn nhẹ (< 2MB)
    khi lưu trữ và đồng bộ qua Git. Chạy VACUUM nếu có bản ghi bị xóa.
    Trả về số lượng bản ghi đã được dọn dẹp.
    """
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    delete_sql = """
    DELETE FROM rentals
    WHERE (posted_time IS NOT NULL AND posted_time < ?)
       OR (posted_time IS NULL AND created_at < ?);
    """
    with get_connection(db_path) as conn:
        cursor = conn.execute(delete_sql, (cutoff, cutoff))
        deleted_count = cursor.rowcount
        conn.commit()

        # Tối ưu kích thước file DB nếu có bản ghi bị xóa
        if deleted_count > 0:
            conn.execute("VACUUM;")
            conn.commit()

        return deleted_count


if __name__ == "__main__":
    init_db()
    print(f"Initialized database successfully at: {DB_PATH}")

    # Test insert
    test_item = {
        "title": "Phòng trọ studio Sơn Trà gần biển",
        "raw_content": "Cho thuê studio full tiện nghi giá 4.5 triệu. LH 0905123456",
        "price_vnd": 4500000,
        "district": "Sơn Trà",
        "room_type": "Studio",
        "url": "https://example.com/test-item-1",
        "source": "Chotot",
        "posted_time": "2026-11-12T10:00:00",
        "image_url": "https://example.com/photo.jpg",
        "phone": "0905123456",
        "area_m2": 32.5,
    }
    inserted = insert_rental(test_item)
    print(f"Insert test item: {inserted}")
    results = get_rentals({"district": "Sơn Trà", "has_phone": True})
    print(f"Found {len(results)} rental(s). First item phone: {results[0].get('phone')}, area: {results[0].get('area_m2')}")
