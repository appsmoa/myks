import os
import json
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

@app.get("/api/bulletins")
def api_list_bulletins(request: Request, q: Optional[str] = None, type: str = "all", year: Optional[str] = None, page: int = 1, page_size: int = 12, key: Optional[str] = None):
    if not check_auth(request, key):
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
    offset = (page - 1) * page_size
    items = database.list_bulletins(query=q, search_type=type, year=year, limit=page_size, offset=offset)
    total_count = database.count_bulletins(query=q, search_type=type, year=year)
    
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
        results.append(record)
        
    return {
        "items": results,
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": (total_count + page_size - 1) // page_size if total_count > 0 else 1
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
    return record

class SettingsPayload(BaseModel):
    gemini_api_key: str
    password: str

@app.post("/api/settings/key")
def api_set_key(payload: SettingsPayload):
    if payload.password.strip() != "4123":
        raise HTTPException(status_code=403, detail="관리자 비밀번호가 올바르지 않습니다.")
    
    key = payload.gemini_api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="Gemini API 키를 입력해 주세요.")
        
    os.environ["GEMINI_API_KEY"] = key
    env_file = os.path.join(BASE_DIR, ".env")
    try:
        set_key(env_file, "GEMINI_API_KEY", key)
    except Exception as e:
        with open(env_file, "w", encoding="utf-8") as f:
            f.write(f"GEMINI_API_KEY={key}\n")
    return {"status": "ok", "message": "Gemini API 키가 성공적으로 저장되었습니다."}

@app.post("/api/crawl")
def api_trigger_crawl(background_tasks: BackgroundTasks, limit: int = 5, use_vision: bool = True):
    def run_job():
        crawler.run_crawler(start_page=1, end_page=1, limit=limit, use_vision=use_vision)
    
    background_tasks.add_task(run_job)
    return {"status": "ok", "message": f"최신 {limit}건 크롤링 및 정리 백그라운드 작업이 시작되었습니다."}

@app.post("/api/bulletins/{b_id}/analyze")
def api_analyze_single(b_id: int):
    item = database.get_bulletin_by_id(b_id)
    if not item:
        raise HTTPException(status_code=404, detail="Bulletin not found")
        
    image_urls = json.loads(item["image_urls"]) if item.get("image_urls") else []
    if not image_urls:
        raise HTTPException(status_code=400, detail="주보 이미지가 없습니다.")
        
    analysis = crawler.extract_bulletin_info_with_gemini(image_urls, item.get("date") or "")
    if not analysis:
        raise HTTPException(status_code=500, detail="주보 데이터 추출에 실패했거나 API 키가 설정되지 않았습니다.")
        
    update_data = {
        "id": b_id,
        "post_num": item["post_num"],
        "title": item["title"],
        "post_date": item["post_date"],
        "author": item["author"],
        "view_count": item["view_count"],
        "detail_url": item["detail_url"],
        "image_urls": image_urls,
        "date": analysis.get("date") or item.get("date"),
        "sermon_title": analysis.get("sermon_title"),
        "scripture": analysis.get("scripture"),
        "preacher": analysis.get("preacher"),
        "servants": analysis.get("servants"),
        "announcements": analysis.get("announcements"),
        "offerings": analysis.get("offerings"),
        "finances": analysis.get("finances"),
        "raw_analysis_json": analysis,
        "status": "analyzed"
    }
    database.save_bulletin(update_data)
    return {"status": "ok", "data": update_data}

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
