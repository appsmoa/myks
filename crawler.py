import os
import re
import json
import base64
import time
import io
import concurrent.futures
import requests
from PIL import Image
from bs4 import BeautifulSoup
import urllib.parse
from dotenv import load_dotenv
from database import init_db, save_bulletin, get_bulletin_by_id
import youtube_matcher
import prayer_time_analyzer

load_dotenv(override=True)

BASE_URL = "https://myks.kr"
BOARD_BASE_URL = f"{BASE_URL}/Board/Index/110"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def get_max_pages():
    try:
        res = requests.get(BOARD_BASE_URL, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        pages_div = soup.find("div", class_="board-pages")
        if pages_div and pages_div.has_attr("data-page_max"):
            return int(pages_div["data-page_max"])
    except Exception as e:
        print(f"[!] Error fetching max page: {e}")
    return 1

def fetch_post_list(page=1):
    url = f"{BOARD_BASE_URL}?page={page}"
    print(f"[*] Fetching page {page}: {url}")
    res = requests.get(url, headers=HEADERS, timeout=10)
    res.encoding = res.apparent_encoding or "utf-8"
    soup = BeautifulSoup(res.text, "html.parser")
    
    posts = []
    board_theme = soup.find("div", class_="board-theme")
    if not board_theme:
        board_theme = soup
        
    table = board_theme.find("table")
    if table:
        tbody = table.find("tbody") or table
        rows = tbody.find_all("tr")
        for row in rows:
            tds = row.find_all("td")
            if len(tds) >= 4:
                num_text = tds[0].get_text(strip=True)
                title_td = row.find("td", class_="document-title") or tds[1]
                a_tag = title_td.find("a")
                if not a_tag or not a_tag.get("href"):
                    continue
                
                href = a_tag["href"]
                detail_url = urllib.parse.urljoin(BASE_URL, href)
                post_id_match = re.search(r"/Detail/\d+/(\d+)", href)
                if not post_id_match:
                    continue
                post_id = int(post_id_match.group(1))
                
                title = a_tag.get_text(strip=True)
                author = tds[2].get_text(strip=True) if len(tds) > 2 else ""
                post_date = tds[3].get_text(strip=True) if len(tds) > 3 else ""
                view_count = int(tds[4].get_text(strip=True)) if len(tds) > 4 and tds[4].get_text(strip=True).isdigit() else 0
                
                post_num = int(num_text) if num_text.isdigit() else post_id
                
                posts.append({
                    "id": post_id,
                    "post_num": post_num,
                    "title": title,
                    "author": author,
                    "post_date": post_date,
                    "view_count": view_count,
                    "detail_url": detail_url
                })
    return posts

def fetch_post_details(post_id, detail_url):
    res = requests.get(detail_url, headers=HEADERS, timeout=10)
    res.encoding = res.apparent_encoding or "utf-8"
    soup = BeautifulSoup(res.text, "html.parser")
    
    image_urls = []
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if "UserData/goldsung/files/110" in src or "dimode.co.kr" in src:
            full_url = urllib.parse.urljoin(BASE_URL, src)
            if full_url not in image_urls:
                image_urls.append(full_url)
                
    if not image_urls:
        content_area = soup.find(class_=lambda c: c and any(k in str(c) for k in ["board-detail", "detail-content", "theme-detail"]))
        if content_area:
            for img in content_area.find_all("img"):
                src = img.get("src", "")
                if src:
                    full_url = urllib.parse.urljoin(BASE_URL, src)
                    if full_url not in image_urls:
                        image_urls.append(full_url)
                        
    return image_urls

def extract_bulletin_info_with_gemini(image_urls, fallback_date=""):
    load_dotenv(override=True)
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("  [!] GEMINI_API_KEY가 설정되지 않아 Vision 분석을 건너뜁니다.")
        return None

    # 주보 이미지들 다운로드 후 인라인 base64 파트 생성
    parts = []
    prompt = f"""
당신은 교회 주보 이미지를 정밀 분석하는 AI 어시스턴트입니다.
첨부된 주보 이미지들(예배 순서, 주보 표지, 교회 소식, 향기로운 예물/헌금 명단, 재정 현황 등)을 읽고 다음 정보를 반드시 유효한 JSON 형식으로 추출해 주세요.

[추출할 JSON 필드]
1. date: 주보 발행 일자 (YYYY-MM-DD 형식, 찾기 어려우면 '{fallback_date}' 참고).
2. sermon_title: 주일 예배 설교 제목 (예: "토브를 맛보는 법, 찾음").
3. scripture: 본문 말씀 성경 구절 (예: "시 34:8~10, 요 15:4~7").
4. preacher: 설교자 성함과 직분 (예: "김호성 목사").
5. servants: 예배별 대표기도자, 찬양대, 특송, 봉사자 명단.
   (대표기도자는 "9시_기도", "11시_기도", "수요_기도"와 같이 예배 시간과 기도자 성함을 명확히 기재해 주세요.)
6. announcements: 교회 소식 및 광고 목록 (배열 형태: [{{"category": "분류", "content": "내용"}}]).
7. offerings: 향기로운 예물 / 헌금자 명단 (항목별로 분류된 오브젝트).
   예: {{
     "십일조": ["홍길동", "김철수(이영희)", ...],
     "감사헌금": ["박영수", "최민지(생일)", ...],
     "선교헌금": ["강현지", "김대성", ...],
     "목적/구제": ["김승호(황문자)", ...]
   }}
8. finances: 재정 현황 (수입 및 지출 항목별 헌금 금액, 단위 '천원'인 경우 실제 금액(원)으로 계산하거나 명시).
   예: {{
     "기준일자": "11월 8일",
     "수입": {{"십일조": 5707000, "주일헌금": 935000, "감사헌금": 1760000, "선교헌금": 350000, "목적헌금": 540000, "총수입": 9898000}},
     "지출": {{"선교": 1550000, "교육": 4142000, "인건비": 2698000, "운영비": 1249000, "총지출": 22608000}}
   }}

반드시 순수 JSON 객체({{...}}) 형태로만 출력하세요. 설명이나 인사말은 일절 제외하세요.
"""
    parts.append({"text": prompt})

    def download_and_optimize(idx_url):
        idx, img_url = idx_url
        try:
            img_res = requests.get(img_url, headers=HEADERS, timeout=12)
            if img_res.status_code == 200:
                raw_bytes = img_res.content
                try:
                    with Image.open(io.BytesIO(raw_bytes)) as img:
                        if img.mode in ("RGBA", "P"):
                            img = img.convert("RGB")
                        max_w = 1600
                        if img.width > max_w:
                            new_h = int(img.height * (max_w / img.width))
                            img = img.resize((max_w, new_h), Image.Resampling.LANCZOS)
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=85, optimize=True)
                        b64_data = base64.b64encode(buf.getvalue()).decode("utf-8")
                        return idx, b64_data
                except Exception:
                    b64_data = base64.b64encode(raw_bytes).decode("utf-8")
                    return idx, b64_data
        except Exception as e:
            print(f"    [!] Failed to download {img_url}: {e}")
        return idx, None

    print(f"  [*] Downloading & optimizing {len(image_urls)} images concurrently...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(image_urls))) as executor:
        results = list(executor.map(download_and_optimize, enumerate(image_urls)))
    
    results.sort(key=lambda x: x[0])
    for _, b64 in results:
        if b64:
            parts.append({
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": b64
                }
            })

    if len(parts) <= 1:
        print("  [!] 주보 이미지를 다운로드하지 못했습니다.")
        return None

    # 다중 API 키 지원 (쉼표 또는 줄바꿈 구분)
    keys = [k.strip() for k in api_key.replace("\n", ",").split(",") if k.strip()]
    if not keys:
        print("  [!] 유효한 Gemini API 키가 없습니다.")
        return None

    # 무료 플랜에서 가장 많은 일일 호출(500 RPD 이상)을 지원하는 Flash-Lite 모델 최우선
    # 503(일시적 과부하) 발생 시 짧게 대기 후 재시도하도록 개선
    models_to_try = [
        "gemini-3.5-flash-lite", 
        "gemini-3.5-flash",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite"
    ]

    for key_idx, current_key in enumerate(keys):
        for model_name in models_to_try:
            for retry in range(2):
                try:
                    print(f"  [*] Calling Gemini Vision API ({model_name}, Key #{key_idx + 1}, try {retry + 1})...")
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={current_key}"
                    payload = {
                        "contents": [{"parts": parts}],
                        "generationConfig": {
                            "response_mime_type": "application/json",
                            "temperature": 0.1
                        }
                    }
                    res = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=18)
                    if res.status_code == 200:
                        res_data = res.json()
                        raw_text = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
                        if raw_text.startswith("```"):
                            raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
                            raw_text = re.sub(r"\s*```$", "", raw_text)
                        return json.loads(raw_text)
                    elif res.status_code == 503:
                        print(f"  [!] {model_name} 일시적 과부하(503). 2초 대기 후 재시도...")
                        time.sleep(2.0)
                        continue
                    elif res.status_code == 429:
                        print(f"  [!] {model_name} 한도 초과(429). 다음 모델/키로 전환합니다.")
                        break
                    else:
                        print(f"  [!] {model_name} HTTP {res.status_code}: {res.text[:120]}")
                        break
                except requests.exceptions.Timeout:
                    print(f"  [!] {model_name} 응답 지연 타임아웃 (18초 초과). 재시도...")
                    time.sleep(1.5)
                    continue
                except Exception as e:
                    print(f"  [!] {model_name} error: {e}")
                    break

    return None

def process_single_post(post, use_vision=True):
    post_id = post["id"]
    
    # 이미 분석/정리가 완료된 주보는 API 호출을 건너뛰어 한도를 절약합니다.
    existing = get_bulletin_by_id(post_id)
    if existing and existing.get("status") == "analyzed":
        print(f"  [i] #{post['post_num']} 이미 정리가 완료된 주보입니다. 건너뜁니다.")
        return existing

    print(f"\n[+] Processing Post #{post['post_num']} (ID: {post_id}): {post['title']}")
    
    image_urls = fetch_post_details(post_id, post["detail_url"])
    print(f"  - Found {len(image_urls)} bulletin images.")
    
    date_match = re.search(r"(\d{4})[.-]?(\d{2})[.-]?(\d{2})", post["title"])
    fallback_date = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}" if date_match else ""
    
    bulletin_record = {
        "id": post_id,
        "post_num": post["post_num"],
        "title": post["title"],
        "post_date": post["post_date"],
        "author": post["author"],
        "view_count": post["view_count"],
        "detail_url": post["detail_url"],
        "image_urls": image_urls,
        "date": fallback_date,
        "sermon_title": None,
        "scripture": None,
        "preacher": None,
        "servants": None,
        "announcements": None,
        "offerings": None,
        "finances": None,
        "raw_analysis_json": None,
        "status": "pending_analysis"
    }

    if use_vision and image_urls:
        analysis = extract_bulletin_info_with_gemini(image_urls, fallback_date)
        if analysis:
            bulletin_record.update({
                "date": analysis.get("date") or fallback_date,
                "sermon_title": analysis.get("sermon_title"),
                "scripture": analysis.get("scripture"),
                "preacher": analysis.get("preacher"),
                "servants": analysis.get("servants"),
                "announcements": analysis.get("announcements"),
                "offerings": analysis.get("offerings"),
                "finances": analysis.get("finances"),
                "raw_analysis_json": analysis,
                "status": "analyzed"
            })
            print(f"  [v] Gemini Vision Extracted Successfully:")
            print(f"      날짜: {bulletin_record['date']}")
            print(f"      설교 제목: {bulletin_record['sermon_title']}")
            print(f"      본문 말씀: {bulletin_record['scripture']}")
            print(f"      설교자: {bulletin_record['preacher']}")
            if bulletin_record.get('servants'):
                print(f"      예배 봉사자: {str(bulletin_record['servants'])[:80]}...")
            if bulletin_record.get('announcements'):
                print(f"      교회 소식: {len(bulletin_record['announcements'])}건")
        else:
            bulletin_record["status"] = "pending_analysis"
            
    # 유튜브 스트림 예배 영상 링크 자동 매칭 및 대표기도 타임스탬프 추출
    try:
        yt_links = youtube_matcher.get_youtube_links_for_bulletin(bulletin_record.get("date") or "")
        if yt_links:
            # Gemini AI를 통한 대표기도 시작 타임스탬프 자동 추출 및 부착
            try:
                servants_data = bulletin_record.get("servants") or {}
                yt_links = prayer_time_analyzer.enrich_youtube_urls_with_prayer_timestamps(yt_links, servants_data)
            except Exception as e:
                print(f"  [!] 기도 타임스탬프 추출 오류: {e}")

            bulletin_record["youtube_urls"] = yt_links
            print(f"      유튜브 영상 매칭 및 기도 타임스탬프 완료: {list(yt_links.keys())}")
    except Exception as e:
        print(f"  [!] YouTube 매칭 오류: {e}")

    save_bulletin(bulletin_record)
    return bulletin_record

def run_crawler(start_page=1, end_page=1, limit=None, use_vision=True):
    init_db()
    total_processed = 0
    if end_page is None or end_page < start_page:
        end_page = get_max_pages()

    for page in range(start_page, end_page + 1):
        posts = fetch_post_list(page)
        if not posts:
            break
        for post in posts:
            process_single_post(post, use_vision=use_vision)
            total_processed += 1
            if limit and total_processed >= limit:
                return

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--end-page", type=int, default=1)
    parser.add_argument("--all-pages", action="store_true")
    parser.add_argument("--no-vision", action="store_true")
    args = parser.parse_args()
    end_p = None if args.all_pages else args.end_page
    run_crawler(start_page=args.start_page, end_page=end_p, limit=args.limit, use_vision=not args.no_vision)
