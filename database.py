import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).resolve().parent / "rentals.db"


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Tạo hoặc lấy kết nối tới SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    """Tạo bảng rentals với các trường dữ liệu theo đặc tả."""
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
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """
    with get_connection(db_path) as conn:
        conn.execute(create_table_sql)
        conn.commit()


def insert_rental(data: Dict[str, Any], db_path: Path = DB_PATH) -> bool:
    """
    Thêm bản ghi mới vào bảng rentals.
    Tự động bỏ qua nếu URL đã tồn tại trong database (INSERT OR IGNORE).
    """
    sql = """
    INSERT OR IGNORE INTO rentals (
        title, raw_content, price_vnd, district, room_type,
        url, source, posted_time, created_at
    ) VALUES (
        :title, :raw_content, :price_vnd, :district, :room_type,
        :url, :source, :posted_time, :created_at
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
        - district (str): Lọc theo quận/huyện
        - room_type (str): Lọc theo loại phòng
        - source (str): Lọc theo nguồn tin cào
        - min_price (int): Giá tối thiểu (VND)
        - max_price (int): Giá tối đa (VND)
        - keyword (str): Tìm kiếm từ khóa trong tiêu đề hoặc nội dung
        - limit (int): Số lượng kết quả tối đa (mặc định 100)
        - offset (int): Vị trí bắt đầu phân trang (mặc định 0)
    """
    filters = filters or {}
    conditions: List[str] = []
    params: List[Any] = []

    # Hỗ trợ cả district (str) lẫn districts (list) cho multiselect
    districts = filters.get("districts")
    district = filters.get("district")
    if districts and isinstance(districts, list) and len(districts) > 0:
        placeholders = ", ".join("?" for _ in districts)
        conditions.append(f"district IN ({placeholders})")
        params.extend(districts)
    elif district and district.lower() != "tất cả":
        conditions.append("district = ?")
        params.append(district)

    room_type = filters.get("room_type")
    if room_type and room_type.lower() != "tất cả":
        conditions.append("room_type = ?")
        params.append(room_type)

    source = filters.get("source")
    if source and source.lower() != "tất cả":
        conditions.append("source = ?")
        params.append(source)

    min_price = filters.get("min_price") or filters.get("min_price_vnd")
    if min_price is not None:
        conditions.append("price_vnd >= ?")
        params.append(int(min_price))

    max_price = filters.get("max_price") or filters.get("max_price_vnd")
    if max_price is not None:
        conditions.append("price_vnd <= ?")
        params.append(int(max_price))

    keyword = filters.get("keyword") or filters.get("q")
    if keyword:
        conditions.append("(title LIKE ? OR raw_content LIKE ?)")
        search_term = f"%{keyword}%"
        params.extend([search_term, search_term])

    # Lọc theo thời gian đăng (ISO datetime string)
    posted_after = filters.get("posted_after")
    if posted_after:
        conditions.append("posted_time >= ?")
        params.append(str(posted_after))

    # Lọc theo danh sách nguồn tin (list) cho checkbox
    sources = filters.get("sources")
    if sources and isinstance(sources, list) and len(sources) > 0:
        placeholders = ", ".join("?" for _ in sources)
        conditions.append(f"source IN ({placeholders})")
        params.extend(sources)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    limit = int(filters.get("limit", 100))
    offset = int(filters.get("offset", 0))

    query = f"""
    SELECT * FROM rentals
    {where_clause}
    ORDER BY created_at DESC
    LIMIT ? OFFSET ?;
    """
    params.extend([limit, offset])

    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


if __name__ == "__main__":
    init_db()
    print(f"Initialized database successfully at: {DB_PATH}")

    # Test insert
    test_item = {
        "title": "Phòng trọ studio Sơn Trà gần biển",
        "raw_content": "Cho thuê studio full tiện nghi giá 4.5 triệu",
        "price_vnd": 4500000,
        "district": "Sơn Trà",
        "room_type": "Studio",
        "url": "https://example.com/item/1",
        "source": "chotot",
        "posted_time": "2026-11-12T10:00:00",
    }
    inserted = insert_rental(test_item)
    print(f"Insert test item: {inserted}")

    # Test insert duplicate url
    duplicate_inserted = insert_rental(test_item)
    print(f"Insert duplicate URL (should be False): {duplicate_inserted}")

    # Test get_rentals
    results = get_rentals({"district": "Sơn Trà", "min_price": 4000000})
    print(f"Found {len(results)} rental(s). First item title: {results[0]['title']}")
