import sqlite3
import json
import os
from typing import Dict, Any, List, Optional

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bulletin.db")

def match_prayer_in_servants(servants_raw: Optional[str], query: Optional[str]) -> int:
    """
    예배 봉사자(servants) JSON 트리 중 오직 '기도'(대표기도) 항목에서만 검색어가 일치하는지 정밀 검사합니다.
    (예배위원, 안내위원, 헌금위원, 차량, 주차, 찬양대, 다음주 등은 완벽하게 배제)
    """
    if not servants_raw or not query:
        return 0
    q = query.strip().lower()
    if not q:
        return 0
    try:
        s = json.loads(servants_raw) if isinstance(servants_raw, str) else servants_raw
    except Exception:
        return 0
    if not isinstance(s, (dict, list)):
        return 0
        
    def walk(obj, path):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if walk(v, path + [str(k)]):
                    return True
        elif isinstance(obj, list):
            for item in obj:
                if walk(item, path):
                    return True
        else:
            val_str = str(obj).lower()
            if q in val_str:
                path_str = ' '.join(path)
                # 다음주 제외 및 오직 '기도' 필드만 허용
                if '다음주' not in path_str and '기도' in path_str:
                    # 안내, 주차, 차량, 헌금, 봉독, 설교, 찬양대 등 다른 봉사직분 철저 배제
                    if not any(x in path_str for x in ['안내', '주차', '차량', '헌금', '봉독', '설교', '찬양대', '반주', '음악', '직원', '교역자']):
                        return True
        return False

    return 1 if walk(s, []) else 0

def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.create_function("match_prayer", 2, match_prayer_in_servants)
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS bulletins (
        id INTEGER PRIMARY KEY,                -- 게시글 상세 ID
        post_num INTEGER,                      -- 게시판 목록 번호
        title TEXT NOT NULL,                   -- 게시판 제목
        post_date TEXT,                        -- 등록일시
        author TEXT,                           -- 작성자
        view_count INTEGER DEFAULT 0,          -- 조회수
        detail_url TEXT NOT NULL,              -- 원본 게시글 링크
        image_urls TEXT,                       -- 주보 원본 이미지 URL 목록 (JSON)
        
        -- Gemini Vision 추출 데이터
        date TEXT,                             -- 주보 일자 (YYYY-MM-DD)
        sermon_title TEXT,                     -- 설교 제목
        scripture TEXT,                        -- 본문 말씀
        preacher TEXT,                         -- 설교자
        servants TEXT,                         -- 예배 봉사자 (JSON)
        announcements TEXT,                    -- 교회 소식 및 광고 (JSON)
        offerings TEXT,                        -- 헌금 명단 (십일조, 감사, 선교, 목적 등 항목별 명단 JSON)
        finances TEXT,                         -- 항목별 헌금 금액 수입/지출 통계 (JSON)
        raw_analysis_json TEXT,                -- 전체 원본 JSON
        
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 기존 DB 테이블에 컬럼이 없을 경우를 대비한 안전한 ALTER TABLE
    cursor.execute("PRAGMA table_info(bulletins);")
    columns = [col[1] for col in cursor.fetchall()]
    if "offerings" not in columns:
        cursor.execute("ALTER TABLE bulletins ADD COLUMN offerings TEXT;")
    if "finances" not in columns:
        cursor.execute("ALTER TABLE bulletins ADD COLUMN finances TEXT;")
        
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bulletins_date ON bulletins(date);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bulletins_sermon ON bulletins(sermon_title);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bulletins_preacher ON bulletins(preacher);")
    
    conn.commit()
    conn.close()

def save_bulletin(data: Dict[str, Any]):
    conn = get_connection()
    cursor = conn.cursor()
    
    image_urls_json = json.dumps(data.get("image_urls", []), ensure_ascii=False) if isinstance(data.get("image_urls"), list) else data.get("image_urls", "[]")
    servants_json = json.dumps(data.get("servants", {}), ensure_ascii=False) if isinstance(data.get("servants"), (dict, list)) else data.get("servants", "")
    announcements_json = json.dumps(data.get("announcements", []), ensure_ascii=False) if isinstance(data.get("announcements"), (dict, list)) else data.get("announcements", "")
    offerings_json = json.dumps(data.get("offerings", {}), ensure_ascii=False) if isinstance(data.get("offerings"), (dict, list)) else data.get("offerings", "")
    finances_json = json.dumps(data.get("finances", {}), ensure_ascii=False) if isinstance(data.get("finances"), (dict, list)) else data.get("finances", "")
    raw_analysis = json.dumps(data.get("raw_analysis_json", {}), ensure_ascii=False) if isinstance(data.get("raw_analysis_json"), dict) else data.get("raw_analysis_json", "")

    cursor.execute("""
    INSERT INTO bulletins (
        id, post_num, title, post_date, author, view_count, detail_url, image_urls,
        date, sermon_title, scripture, preacher, servants, announcements, offerings, finances, raw_analysis_json,
        status, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(id) DO UPDATE SET
        post_num = excluded.post_num,
        title = excluded.title,
        post_date = excluded.post_date,
        author = excluded.author,
        view_count = excluded.view_count,
        detail_url = excluded.detail_url,
        image_urls = excluded.image_urls,
        date = COALESCE(excluded.date, bulletins.date),
        sermon_title = COALESCE(excluded.sermon_title, bulletins.sermon_title),
        scripture = COALESCE(excluded.scripture, bulletins.scripture),
        preacher = COALESCE(excluded.preacher, bulletins.preacher),
        servants = COALESCE(excluded.servants, bulletins.servants),
        announcements = COALESCE(excluded.announcements, bulletins.announcements),
        offerings = COALESCE(excluded.offerings, bulletins.offerings),
        finances = COALESCE(excluded.finances, bulletins.finances),
        raw_analysis_json = COALESCE(excluded.raw_analysis_json, bulletins.raw_analysis_json),
        status = excluded.status,
        updated_at = CURRENT_TIMESTAMP
    """, (
        data["id"],
        data.get("post_num"),
        data.get("title", ""),
        data.get("post_date", ""),
        data.get("author", ""),
        data.get("view_count", 0),
        data.get("detail_url", ""),
        image_urls_json,
        data.get("date"),
        data.get("sermon_title"),
        data.get("scripture"),
        data.get("preacher"),
        servants_json,
        announcements_json,
        offerings_json,
        finances_json,
        raw_analysis,
        data.get("status", "pending")
    ))
    
    conn.commit()
    conn.close()

def get_bulletin_by_id(b_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bulletins WHERE id = ?", (b_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def list_bulletins(query: Optional[str] = None, search_type: str = "all", year: Optional[str] = None, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    
    conditions = []
    params = []
    
    if year and year != "all":
        conditions.append("date LIKE ?")
        params.append(f"{year}%")
        
    if query:
        search_pattern = f"%{query}%"
        if search_type == "sermon":
            conditions.append("sermon_title LIKE ?")
            params.append(search_pattern)
        elif search_type == "prayer":
            conditions.append("match_prayer(servants, ?) = 1")
            params.append(query)
        elif search_type == "preacher":
            conditions.append("preacher LIKE ?")
            params.append(search_pattern)
        elif search_type == "scripture":
            conditions.append("scripture LIKE ?")
            params.append(search_pattern)
        elif search_type == "announcement":
            conditions.append("announcements LIKE ?")
            params.append(search_pattern)
        elif search_type == "offering":
            conditions.append("offerings LIKE ?")
            params.append(search_pattern)
        else: # all
            conditions.append("""(
                title LIKE ? OR sermon_title LIKE ? OR scripture LIKE ? OR preacher LIKE ? 
                OR announcements LIKE ? OR servants LIKE ? OR offerings LIKE ? OR finances LIKE ?
            )""")
            params.extend([search_pattern] * 8)
            
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT * FROM bulletins {where_clause} ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    cursor.execute(sql, tuple(params))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def count_bulletins(query: Optional[str] = None, search_type: str = "all", year: Optional[str] = None) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    
    conditions = []
    params = []
    
    if year and year != "all":
        conditions.append("date LIKE ?")
        params.append(f"{year}%")
        
    if query:
        search_pattern = f"%{query}%"
        if search_type == "sermon":
            conditions.append("sermon_title LIKE ?")
            params.append(search_pattern)
        elif search_type == "prayer":
            conditions.append("match_prayer(servants, ?) = 1")
            params.append(query)
        elif search_type == "preacher":
            conditions.append("preacher LIKE ?")
            params.append(search_pattern)
        elif search_type == "scripture":
            conditions.append("scripture LIKE ?")
            params.append(search_pattern)
        elif search_type == "announcement":
            conditions.append("announcements LIKE ?")
            params.append(search_pattern)
        elif search_type == "offering":
            conditions.append("offerings LIKE ?")
            params.append(search_pattern)
        else: # all
            conditions.append("""(
                title LIKE ? OR sermon_title LIKE ? OR scripture LIKE ? OR preacher LIKE ? 
                OR announcements LIKE ? OR servants LIKE ? OR offerings LIKE ? OR finances LIKE ?
            )""")
            params.extend([search_pattern] * 8)
            
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT COUNT(*) FROM bulletins {where_clause}"
    
    cursor.execute(sql, tuple(params))
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_available_years() -> List[str]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT date FROM bulletins WHERE date IS NOT NULL AND date != ''")
    dates = [r[0] for r in cursor.fetchall()]
    conn.close()
    years = sorted(list(set([d.split('-')[0] for d in dates if len(d) >= 4 and d[:4].isdigit()])), reverse=True)
    return years

if __name__ == "__main__":
    init_db()
    print("[*] DB migrated successfully.")
