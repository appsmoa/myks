import os
import json
import re
import time
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, Request, Query, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from dotenv import load_dotenv, set_key

import database
import crawler
import batch_analyze
import github_sync
import youtube_matcher
import prayer_time_analyzer

load_dotenv()

app = FastAPI(title="금성교회 주보 아카이브 & 검색 시스템")

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    # 검색엔진 및 AI 크롤러 색인/캐시 전면 차단
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    return response

@app.get("/robots.txt", response_class=PlainTextResponse)
def get_robots_txt():
    return (
        "User-agent: *\n"
        "Disallow: /\n\n"
        "# Block AI Scrapers & Crawlers\n"
        "User-agent: GPTBot\n"
        "Disallow: /\n"
        "User-agent: ChatGPT-User\n"
        "Disallow: /\n"
        "User-agent: CCBot\n"
        "Disallow: /\n"
        "User-agent: Google-Extended\n"
        "Disallow: /\n"
        "User-agent: ClaudeBot\n"
        "Disallow: /\n"
        "User-agent: anthropic-ai\n"
        "Disallow: /\n"
        "User-agent: Bytespider\n"
        "Disallow: /\n"
        "User-agent: PerplexityBot\n"
        "Disallow: /\n"
        "User-agent: FacebookBot\n"
        "Disallow: /\n"
    )

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

templates = Jinja2Templates(directory=TEMPLATES_DIR)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

def check_auth(request: Request, key: Optional[str] = None) -> bool:
    if key and key.strip().lower() == "myks":
        return True
    if request.cookies.get("myks_auth", "").strip().lower() == "myks":
        return True
    if request.headers.get("X-Myks-Key", "").strip().lower() == "myks":
        return True
    return False

@app.on_event("startup")
def on_startup():
    database.init_db()

@app.post("/api/auth/verify")
def api_verify_auth(data: dict):
    input_key = data.get("key", "").strip().lower()
    if input_key == "myks":
        res = JSONResponse({"success": True})
        res.set_cookie(key="myks_auth", value="myks", max_age=31536000, httponly=False, samesite="lax")
        return res
    return JSONResponse({"success": False, "message": "암호가 올바르지 않습니다."}, status_code=401)

@app.get("/", response_class=HTMLResponse)
def index(request: Request, key: Optional[str] = None):
    is_authenticated = check_auth(request, key)
    has_api_key = bool(os.getenv("GEMINI_API_KEY", "").strip())
    response = templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"has_api_key": has_api_key, "is_authenticated": is_authenticated}
    )
    if key and key.strip().lower() == "myks":
        response.set_cookie(key="myks_auth", value="myks", max_age=31536000, httponly=False, samesite="lax")
    return response

@app.get("/api/bulletins/calendar")
def api_get_calendar_dates(request: Request, key: Optional[str] = None):
    if not check_auth(request, key):
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
    return database.get_bulletin_calendar_dates()

@app.get("/api/bulletins")
def api_list_bulletins(request: Request, q: Optional[str] = None, type: str = "all", year: Optional[str] = None, date: Optional[str] = None, page: int = 1, page_size: int = 12, key: Optional[str] = None):
    if not check_auth(request, key):
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
    offset = (page - 1) * page_size
    items = database.list_bulletins(query=q, search_type=type, year=year, date=date, limit=page_size, offset=offset)
    total_count = database.count_bulletins(query=q, search_type=type, year=year, date=date)
    finance_summary = database.get_finance_summary(query=q, search_type=type, year=year, date=date)
    
    # JSON 직렬화 정제
    results = []
    for item in items:
        record = dict(item)
        record["image_urls"] = json.loads(record["image_urls"]) if record.get("image_urls") else []
        try:
            record["servants"] = json.loads(record["servants"]) if record.get("servants") and record["servants"].startswith("{") else record.get("servants")
        except:
            pass
        try:
            record["announcements"] = json.loads(record["announcements"]) if record.get("announcements") and record["announcements"].startswith("[") else record.get("announcements")
        except:
            pass
        try:
            record["offerings"] = json.loads(record["offerings"]) if record.get("offerings") and record["offerings"].startswith("{") else record.get("offerings")
        except:
            pass
        try:
            record["finances"] = json.loads(record["finances"]) if record.get("finances") and record["finances"].startswith("{") else record.get("finances")
        except:
            pass

        # 유튜브 링크 로드 및 최근 주보 자동 매칭
        yt = {}
        if record.get("youtube_urls"):
            try:
                yt = json.loads(record["youtube_urls"]) if isinstance(record["youtube_urls"], str) else record["youtube_urls"]
            except:
                yt = {}
        if not yt and record.get("date"):
            try:
                b_dt = datetime.strptime(record["date"][:10], "%Y-%m-%d")
                if (datetime.now() - b_dt).days < 90:
                    yt = youtube_matcher.get_youtube_links_for_bulletin(record["date"])
            except:
                pass
        record["youtube_urls"] = yt or {}
        results.append(record)
        
    return {
        "items": results,
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": (total_count + page_size - 1) // page_size if total_count > 0 else 1,
        "finance_summary": finance_summary
    }

@app.get("/api/years")
def api_get_years():
    return database.get_available_years()

@app.get("/api/bulletins/{b_id}")
def api_get_bulletin(b_id: int, request: Request, key: Optional[str] = None):
    if not check_auth(request, key):
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
    item = database.get_bulletin_by_id(b_id)
    if not item:
        raise HTTPException(status_code=404, detail="Bulletin not found")
        
    record = dict(item)
    record["image_urls"] = json.loads(record["image_urls"]) if record.get("image_urls") else []
    try:
        record["servants"] = json.loads(record["servants"]) if record.get("servants") and record["servants"].startswith("{") else record.get("servants")
    except:
        pass
    try:
        record["announcements"] = json.loads(record["announcements"]) if record.get("announcements") and record["announcements"].startswith("[") else record.get("announcements")
    except:
        pass
    try:
        record["offerings"] = json.loads(record["offerings"]) if record.get("offerings") and record["offerings"].startswith("{") else record.get("offerings")
    except:
        pass
    try:
        record["finances"] = json.loads(record["finances"]) if record.get("finances") and record["finances"].startswith("{") else record.get("finances")
    except:
        pass
    # 유튜브 링크 로드 및 자동 매칭
    yt = {}
    if record.get("youtube_urls"):
        try:
            yt = json.loads(record["youtube_urls"]) if isinstance(record["youtube_urls"], str) else record["youtube_urls"]
        except:
            yt = {}
    if not yt and record.get("date"):
        try:
            yt = youtube_matcher.get_youtube_links_for_bulletin(record["date"])
        except:
            pass
    record["youtube_urls"] = yt or {}
    return record

class SettingsPayload(BaseModel):
    gemini_api_key: Optional[str] = None
    github_token: Optional[str] = None
    password: str

@app.post("/api/settings/key")
def api_set_key(payload: SettingsPayload):
    if payload.password.strip() != "4123":
        raise HTTPException(status_code=403, detail="관리자 비밀번호가 올바르지 않습니다.")
    
    env_file = os.path.join(BASE_DIR, ".env")
    updated_items = []
    
    if payload.gemini_api_key and payload.gemini_api_key.strip():
        key = payload.gemini_api_key.strip()
        os.environ["GEMINI_API_KEY"] = key
        try:
            set_key(env_file, "GEMINI_API_KEY", key)
        except Exception:
            pass
        updated_items.append("Gemini API 키")
        
    if payload.github_token and payload.github_token.strip():
        g_token = payload.github_token.strip()
        os.environ["GITHUB_TOKEN"] = g_token
        try:
            set_key(env_file, "GITHUB_TOKEN", g_token)
        except Exception:
            pass
        updated_items.append("GitHub 토큰")
        
    if not updated_items:
        raise HTTPException(status_code=400, detail="저장할 키 또는 토큰을 입력해 주세요.")
        
    return {"status": "ok", "message": f"{', '.join(updated_items)}가 성공적으로 저장되었습니다."}

@app.post("/api/sync-github")
def api_sync_github(background_tasks: BackgroundTasks):
    def run_sync():
        github_sync.sync_db_to_github()
    background_tasks.add_task(run_sync)
    return {"status": "ok", "message": "GitHub로 최신 DB 자동 저장을 시작했습니다."}

@app.post("/api/crawl")
def api_trigger_crawl(background_tasks: BackgroundTasks, limit: int = 5, use_vision: bool = True):
    def run_job():
        crawler.run_crawler(start_page=1, end_page=1, limit=limit, use_vision=use_vision)
        # 크롤링 및 DB 저장 완료 후, 자동으로 GitHub에 최신 bulletin.db 커밋 & 푸시!
        try:
            res = github_sync.sync_db_to_github()
            print("[Auto-Sync Result]", res)
        except Exception as e:
            print(f"[GitHub Auto-Sync Error] {e}")
    
    background_tasks.add_task(run_job)
    return {"status": "ok", "message": f"최신 {limit}건 크롤링 및 GitHub 자동 동기화 작업이 시작되었습니다."}

# 개별 주보 재정리 실시간 진행 상황 관리 (1단계: 이미지 분석 -> 2단계: 유튜브 매칭 -> 3단계: 기도영상 분석 -> 4단계: 완료)
bulletin_analysis_jobs = {}

def run_full_reanalyze_pipeline(b_id: int):
    item = database.get_bulletin_by_id(b_id)
    if not item:
        err_obj = {
            "status": "error",
            "stage": 1,
            "message": "주보를 찾을 수 없습니다.",
            "updated_at": time.time(),
            "stages": [
                {"name": "주보 이미지 Vision 분석", "status": "error", "detail": "주보 레코드가 존재하지 않습니다."},
                {"name": "유튜브 예배 영상 매칭", "status": "pending", "detail": ""},
                {"name": "Gemini 영상 대표기도 탐색", "status": "pending", "detail": ""},
                {"name": "데이터 저장 및 완료", "status": "pending", "detail": ""}
            ]
        }
        bulletin_analysis_jobs[b_id] = err_obj
        return

    real_id = item["id"]
    post_num = item.get("post_num")

    def set_job_state(obj):
        bulletin_analysis_jobs[real_id] = obj
        if post_num:
            bulletin_analysis_jobs[post_num] = obj
        if b_id != real_id:
            bulletin_analysis_jobs[b_id] = obj

    image_urls = json.loads(item["image_urls"]) if item.get("image_urls") else []
    if not image_urls:
        err_obj = {
            "status": "error",
            "stage": 1,
            "message": "주보 이미지가 등록되어 있지 않습니다.",
            "updated_at": time.time(),
            "stages": [
                {"name": "주보 이미지 Vision 분석", "status": "error", "detail": "주보 이미지가 등록되어 있지 않습니다."},
                {"name": "유튜브 예배 영상 매칭", "status": "pending", "detail": ""},
                {"name": "Gemini 영상 대표기도 탐색", "status": "pending", "detail": ""},
                {"name": "데이터 저장 및 완료", "status": "pending", "detail": ""}
            ]
        }
        set_job_state(err_obj)
        return

    job_state = {
        "status": "running",
        "stage": 1,
        "message": "1단계: Gemini Vision으로 주보 이미지 텍스트 분석 중...",
        "updated_at": time.time(),
        "stages": [
            {"name": "주보 이미지 Vision 분석", "status": "running", "detail": "설교, 본문, 기도자, 헌금 추출 중 (약 5~10초)"},
            {"name": "유튜브 예배 영상 매칭", "status": "pending", "detail": "대기 중"},
            {"name": "Gemini 영상 대표기도 탐색", "status": "pending", "detail": "대기 중"},
            {"name": "데이터 저장 및 완료", "status": "pending", "detail": "대기 중"}
        ]
    }
    set_job_state(job_state)

    try:
        # [1단계] 주보 이미지 Vision 분석
        analysis = crawler.extract_bulletin_info_with_gemini(image_urls, item.get("date") or "")
        if not analysis:
            raise Exception("Gemini API에서 주보 데이터를 추출하지 못했습니다. API 키 설정을 확인해 주세요.")

        sermon_title = analysis.get("sermon_title") or "제목 미상"
        target_date = analysis.get("date") or item.get("date") or ""

        job_state["stages"][0]["status"] = "completed"
        job_state["stages"][0]["detail"] = f"설교: '{sermon_title[:20]}' 본문/기도자 추출 완료"
        
        # [2단계] 유튜브 예배 영상 매칭
        job_state["stage"] = 2
        job_state["message"] = "2단계: 유튜브 채널에서 해당 날짜 예배 영상 찾는 중..."
        job_state["stages"][1]["status"] = "running"
        job_state["stages"][1]["detail"] = f"{target_date} 예배 실시간 영상 자동 매칭 중"
        job_state["updated_at"] = time.time()
        set_job_state(job_state)

        yt_links = youtube_matcher.get_youtube_links_for_bulletin(target_date)
        yt_count = len(yt_links) if yt_links else 0
        job_state["stages"][1]["status"] = "completed"
        job_state["stages"][1]["detail"] = f"예배 영상 {yt_count}건 매칭 완료" if yt_count > 0 else "해당 날짜 영상 없음"

        # 1차 중간 DB 저장 (이미지 텍스트와 영상 링크 즉시 반영)
        update_data = {
            "id": real_id,
            "post_num": item["post_num"],
            "title": item["title"],
            "post_date": item["post_date"],
            "author": item["author"],
            "view_count": item["view_count"],
            "detail_url": item["detail_url"],
            "image_urls": image_urls,
            "date": target_date,
            "sermon_title": analysis.get("sermon_title"),
            "scripture": analysis.get("scripture"),
            "preacher": analysis.get("preacher"),
            "servants": analysis.get("servants"),
            "announcements": analysis.get("announcements"),
            "offerings": analysis.get("offerings"),
            "finances": analysis.get("finances"),
            "youtube_urls": yt_links if yt_links else item.get("youtube_urls"),
            "raw_analysis_json": analysis,
            "status": "analyzed"
        }
        database.save_bulletin(update_data)

        # [3단계] Gemini AI 영상 대표기도 탐색
        job_state["stage"] = 3
        job_state["updated_at"] = time.time()

        if yt_links and analysis.get("servants"):
            job_state["message"] = "3단계: Gemini AI가 유튜브 영상에서 대표기도 시작 분:초 탐색 중... (약 25~45초 소요)"
            job_state["stages"][2]["status"] = "running"
            job_state["stages"][2]["detail"] = "유튜브 영상 타임스탬프 분석 중... 잠시만 기다려 주세요."
            set_job_state(job_state)
            
            try:
                parsed_servants = analysis.get("servants")
                if isinstance(parsed_servants, str):
                    try:
                        parsed_servants = json.loads(parsed_servants)
                    except Exception:
                        pass
                
                enriched = prayer_time_analyzer.enrich_youtube_urls_with_prayer_timestamps(yt_links, parsed_servants or {})
                if enriched:
                    conn = database.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("UPDATE bulletins SET youtube_urls = ? WHERE id = ?", (json.dumps(enriched, ensure_ascii=False), real_id))
                    conn.commit()
                    conn.close()

                    # 타임스탬프 분:초 요약 생성
                    found_times = []
                    for s_name, link in enriched.items():
                        m = re.search(r'[?&]t=(\d+)s?', link)
                        if m:
                            total_s = int(m.group(1))
                            found_times.append(f"{s_name}({total_s//60:02d}:{total_s%60:02d})")
                    time_summary = ", ".join(found_times) if found_times else "타임스탬프 연결됨"
                    job_state["stages"][2]["status"] = "completed"
                    job_state["stages"][2]["detail"] = f"대표기도 위치 발견: {time_summary}"
                else:
                    job_state["stages"][2]["status"] = "completed"
                    job_state["stages"][2]["detail"] = "기도자 매칭 정보 없음 또는 기본 영상 링크 유지"
            except Exception as pe:
                job_state["stages"][2]["status"] = "completed"
                job_state["stages"][2]["detail"] = f"영상 분석 생략 (사유: {str(pe)[:40]})"
        else:
            job_state["stages"][2]["status"] = "completed"
            job_state["stages"][2]["detail"] = "영상 링크 또는 기도자 정보 없음으로 스킵"

        # [4단계] 데이터 최종 저장 및 완료
        job_state["stage"] = 4
        job_state["message"] = "4단계: 모든 데이터 정리 및 영상 타임스탬프 연결 완료!"
        job_state["stages"][3]["status"] = "completed"
        job_state["stages"][3]["detail"] = "주보 데이터 및 기도영상 링크가 성공적으로 반영되었습니다."
        job_state["status"] = "completed"
        job_state["updated_at"] = time.time()
        set_job_state(job_state)

        try:
            github_sync.sync_db_to_github()
        except Exception as ge:
            print(f"[Sync Warning] {ge}")

    except Exception as e:
        err_msg = str(e)
        job_state["status"] = "error"
        job_state["message"] = f"오류 발생: {err_msg}"
        job_state["updated_at"] = time.time()
        for st in job_state["stages"]:
            if st["status"] == "running":
                st["status"] = "error"
                st["detail"] = err_msg
        set_job_state(job_state)

@app.post("/api/bulletins/{b_id}/analyze")
def api_analyze_single(b_id: int, background_tasks: BackgroundTasks):
    item = database.get_bulletin_by_id(b_id)
    if not item:
        raise HTTPException(status_code=404, detail="Bulletin not found")

    job = bulletin_analysis_jobs.get(item["id"]) or bulletin_analysis_jobs.get(b_id)
    if job and job.get("status") == "running" and (time.time() - job.get("updated_at", 0) < 180):
        return {"status": "already_running", "message": "이미 재정리 작업이 진행 중입니다.", "job": job}

    background_tasks.add_task(run_full_reanalyze_pipeline, b_id)
    return {"status": "started", "message": "주보 및 기도영상 재정리가 백그라운드에서 시작되었습니다."}

@app.get("/api/bulletins/{b_id}/analyze-status")
def api_get_bulletin_analyze_status(b_id: int):
    item = database.get_bulletin_by_id(b_id)
    if item:
        job = bulletin_analysis_jobs.get(item["id"]) or bulletin_analysis_jobs.get(item.get("post_num")) or bulletin_analysis_jobs.get(b_id)
        if job:
            return job
        is_analyzed = item.get("status") == "analyzed"
        return {
            "status": "completed" if is_analyzed else "idle",
            "stage": 4 if is_analyzed else 0,
            "message": "정리 완료됨" if is_analyzed else "정리 대기 상태",
            "stages": []
        }

    job = bulletin_analysis_jobs.get(b_id)
    if job:
        return job
    return {"status": "none", "stage": 0, "message": "작업 내역 없음", "stages": []}

@app.get("/api/analysis-status")
def api_analysis_status():
    conn = database.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM bulletins")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM bulletins WHERE status = 'analyzed'")
    analyzed = cursor.fetchone()[0]
    conn.close()
    return {
        "total": total,
        "analyzed": analyzed,
        "pending": total - analyzed,
        "is_running": batch_analyze.is_running,
        "progress_percent": round((analyzed / total * 100), 1) if total > 0 else 0
    }

@app.post("/api/batch-analyze")
def api_trigger_batch_analyze(background_tasks: BackgroundTasks, limit: Optional[int] = None):
    if batch_analyze.is_running:
        return {"status": "already_running", "message": "이미 일괄 정리 작업이 진행 중입니다."}
    
    background_tasks.add_task(batch_analyze.run_batch_analysis, limit=limit, delay=2.5)
    return {"status": "ok", "message": "백그라운드에서 주보 일괄 정리를 시작했습니다."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=False)
