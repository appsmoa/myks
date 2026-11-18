import sqlite3
import json
import os
import re
from typing import Dict, Any, List, Optional

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bulletin.db")

# 개역개정 성경 66권 축약어 및 별칭 매핑 테이블
BIBLE_BOOKS = [
    ('요한일서', '요일', ['요한일서', '요한1서', '요한 1서', '요일']),
    ('요한이서', '요이', ['요한이서', '요한2서', '요한 2서', '요이']),
    ('요한삼서', '요삼', ['요한삼서', '요한3서', '요한 3서', '요삼']),
    ('사무엘상', '삼상', ['사무엘상', '사무엘 상', '삼상']),
    ('사무엘하', '삼하', ['사무엘하', '사무엘 하', '삼하']),
    ('열왕기상', '왕상', ['열왕기상', '열왕기 상', '왕상']),
    ('열왕기하', '왕하', ['열왕기하', '열왕기 하', '왕하']),
    ('역대상', '대상', ['역대상', '역대 상', '대상']),
    ('역대하', '대하', ['역대하', '역대 하', '대하']),
    ('고린도전서', '고전', ['고린도전서', '고린도전', '고린도 전서', '고린도 전', '고전']),
    ('고린도후서', '고후', ['고린도후서', '고린도후', '고린도 후서', '고린도 후', '고후']),
    ('데살로니가전서', '살전', ['데살로니가전서', '데살로니가전', '살전']),
    ('데살로니가후서', '살후', ['데살로니가후서', '데살로니가후', '살후']),
    ('디모데전서', '딤전', ['디모데전서', '디모데전', '딤전']),
    ('디모데후서', '딤후', ['디모데후서', '디모데후', '딤후']),
    ('베드로전서', '벧전', ['베드로전서', '베드로전', '벧전']),
    ('베드로후서', '벧후', ['베드로후서', '베드로후', '벧후']),
    ('예레미야애가', '애', ['예레미야애가', '예레미야 애가', '애가', '애']),
    ('요한계시록', '계', ['요한계시록', '계시록', '계']),
    ('사도행전', '행', ['사도행전', '사도', '행전', '행']),
    ('마태복음', '마', ['마태복음', '마태', '마']),
    ('마가복음', '막', ['마가복음', '마가', '막']),
    ('누가복음', '눅', ['누가복음', '누가', '눅']),
    ('요한복음', '요', ['요한복음', '요한', '요']),
    ('로마서', '롬', ['로마서', '로마', '롬']),
    ('갈라디아서', '갈', ['갈라디아서', '갈라디아', '갈']),
    ('에베소서', '엡', ['에베소서', '에베소', '엡']),
    ('빌립보서', '빌', ['빌립보서', '빌립보', '빌']),
    ('골로새서', '골', ['골로새서', '골로새', '골']),
    ('디도서', '딛', ['디도서', '디도', '딛']),
    ('빌레몬서', '몬', ['빌레몬서', '빌레몬', '몬']),
    ('히브리서', '히', ['히브리서', '히브리', '히']),
    ('야고보서', '약', ['야고보서', '야고보', '약']),
    ('유다서', '유', ['유다서', '유다', '유']),
    ('창세기', '창', ['창세기', '창세', '창']),
    ('출애굽기', '출', ['출애굽기', '출애굽', '출']),
    ('레위기', '레', ['레위기', '레위', '레']),
    ('민수기', '민', ['민수기', '민수', '민']),
    ('신명기', '신', ['신명기', '신명', '신']),
    ('여호수아', '수', ['여호수아', '여호수아서', '수아', '수']),
    ('사사기', '삿', ['사사기', '사사', '삿']),
    ('룻기', '룻', ['룻기', '룻']),
    ('에스라', '스', ['에스라', '스라', '스']),
    ('느헤미야', '느', ['느헤미야', '느헤', '느']),
    ('에스더', '에', ['에스더', '에스', '에']),
    ('욥기', '욥', ['욥기', '욥']),
    ('시편', '시', ['시편', '시']),
    ('잠언', '잠', ['잠언', '잠']),
    ('전도서', '전', ['전도서', '전도', '전']),
    ('아가', '아', ['아가서', '아가', '아']),
    ('이사야', '사', ['이사야', '이사', '사']),
    ('예레미야', '렘', ['예레미야', '예레', '렘']),
    ('에스겔', '겔', ['에스겔', '에스겔서', '겔']),
    ('다니엘', '단', ['다니엘', '다니', '단']),
    ('호세아', '호', ['호세아', '호세', '호']),
    ('요엘', '욜', ['요엘', '욜']),
    ('아모스', '암', ['아모스', '아모', '암']),
    ('오바댜', '옵', ['오바댜', '오바', '옵']),
    ('요나', '욘', ['요나', '욘']),
    ('미가', '미', ['미가', '미']),
    ('나훔', '나', ['나훔', '나']),
    ('하박국', '합', ['하박국', '하박', '합']),
    ('스바냐', '습', ['스바냐', '스바', '습']),
    ('학개', '학', ['학개', '학']),
    ('스가랴', '슥', ['스가랴', '스가', '슥']),
    ('말라기', '말', ['말라기', '말라', '말'])
]

def _parse_ref_target(s: str):
    m = re.match(r'^(\d+)(?::(\d+)(?:[~\-](\d+))?)?', s.strip())
    if not m:
        return None, None, None
    ch = int(m.group(1))
    v_start = int(m.group(2)) if m.group(2) else None
    v_end = int(m.group(3)) if m.group(3) else v_start
    if v_start is None:
        m_range = re.match(r'^(\d+)[~\-](\d+)', s.strip())
        if m_range:
            v_start = int(m_range.group(1))
            v_end = int(m_range.group(2))
    return ch, v_start, v_end

def _parse_query_ref(q: str):
    if not q:
        return None, None
    q = re.sub(r'장', ':', q)
    q = re.sub(r'편', '', q)
    q = re.sub(r'절.*', '', q)
    q = re.sub(r'[^\d:]', '', q).strip(':')
    if not q:
        return None, None
    parts = q.split(':')
    ch = int(parts[0]) if parts[0].isdigit() else None
    v = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    return ch, v

def match_scripture_in_text(scripture_raw: Optional[str], query: Optional[str]) -> int:
    """
    본문 성경 구절(scripture)에서 성경 66권 풀네임(마태복음, 시편 등) 및 축약어(마, 시 등),
    장/절 검색을 상호 매핑하여 정밀 검사합니다.
    """
    if not scripture_raw or not query:
        return 0
    s = str(scripture_raw).strip()
    q = str(query).strip()
    if not s or not q:
        return 0
        
    # 1. 단순 부분문자열 포함 검사
    if q.lower() in s.lower():
        return 1

    # 2. 검색어에서 성경 책 이름(별칭/풀네임) 매칭
    matched_abbr = None
    remaining_q = q
    for full_name, abbr, aliases in BIBLE_BOOKS:
        candidates = sorted(set([full_name, abbr] + aliases), key=len, reverse=True)
        for cand in candidates:
            if remaining_q.startswith(cand):
                matched_abbr = abbr
                remaining_q = remaining_q[len(cand):].strip()
                break
        if matched_abbr:
            break

    if not matched_abbr:
        return 0

    q_ch, q_v = _parse_query_ref(remaining_q)

    # 본문(s)에서 matched_abbr로 시작하는 구절 찾기
    pattern = rf'(?:^|[,\s/|]){re.escape(matched_abbr)}\s*[:\s]*([0-9:~\-, ]+)'
    matches = list(re.finditer(pattern, s))
    if not matches:
        if q_ch is None:
            simple_pat = rf'(?:^|[,\s/|]){re.escape(matched_abbr)}(?:\b|[,\s/|:]|$)'
            return 1 if re.search(simple_pat, s) else 0
        return 0

    if q_ch is None:
        return 1

    for m in matches:
        raw_ref = m.group(1).strip()
        segments = [x.strip() for x in raw_ref.split(',')]
        curr_ch = None
        for seg in segments:
            t_ch, t_vs, t_ve = _parse_ref_target(seg)
            if t_ch is not None:
                curr_ch = t_ch
            elif curr_ch is not None:
                m_verse = re.match(r'^(\d+)(?:[~\-](\d+))?', seg)
                if m_verse:
                    t_vs = int(m_verse.group(1))
                    t_ve = int(m_verse.group(2)) if m_verse.group(2) else t_vs

            if curr_ch == q_ch:
                if q_v is None:
                    return 1
                if t_vs is not None:
                    end = t_ve if t_ve is not None else t_vs
                    if t_vs <= q_v <= end:
                        return 1

    return 0

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
    conn.create_function("match_scripture", 2, match_scripture_in_text)
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
            conditions.append("match_scripture(scripture, ?) = 1")
            params.append(query)
        elif search_type == "announcement":
            conditions.append("announcements LIKE ?")
            params.append(search_pattern)
        elif search_type == "offering":
            conditions.append("offerings LIKE ?")
            params.append(search_pattern)
        else: # all
            conditions.append("""(
                title LIKE ? OR sermon_title LIKE ? OR match_scripture(scripture, ?) = 1 OR preacher LIKE ? 
                OR announcements LIKE ? OR servants LIKE ? OR offerings LIKE ? OR finances LIKE ?
            )""")
            params.extend([search_pattern, search_pattern, query, search_pattern, search_pattern, search_pattern, search_pattern, search_pattern])
            
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
            conditions.append("match_scripture(scripture, ?) = 1")
            params.append(query)
        elif search_type == "announcement":
            conditions.append("announcements LIKE ?")
            params.append(search_pattern)
        elif search_type == "offering":
            conditions.append("offerings LIKE ?")
            params.append(search_pattern)
        else: # all
            conditions.append("""(
                title LIKE ? OR sermon_title LIKE ? OR match_scripture(scripture, ?) = 1 OR preacher LIKE ? 
                OR announcements LIKE ? OR servants LIKE ? OR offerings LIKE ? OR finances LIKE ?
            )""")
            params.extend([search_pattern, search_pattern, query, search_pattern, search_pattern, search_pattern, search_pattern, search_pattern])
            
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
