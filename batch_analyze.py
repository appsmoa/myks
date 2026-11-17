import os
import json
import time
import argparse
from dotenv import load_dotenv

load_dotenv(override=True)

import database
import crawler

is_running = False

def run_batch_analysis(limit=None, delay=2.5):
    global is_running
    if is_running:
        print("[!] 이미 자동 정리 작업이 실행 중입니다.")
        return
        
    is_running = True
    try:
        database.init_db()
        conn = database.get_connection()
        cursor = conn.cursor()
        
        # 미정리 주보 최신순 조회
        cursor.execute("SELECT * FROM bulletins WHERE status != 'analyzed' ORDER BY id DESC")
        pending_items = [dict(r) for r in cursor.fetchall()]
        conn.close()
        
        total_pending = len(pending_items)
        print(f"\n==================================================")
        print(f"[*] 미정리 주보 고속 자동 정리 시작 (총 대상: {total_pending}건)")
        print(f"[*] 터보 모드 최적화: 건당 약 {delay}초 간격으로 진행됩니다.")
        print(f"==================================================\n")
        
        success_count = 0
        target_items = pending_items[:limit] if limit else pending_items
        
        for idx, b in enumerate(target_items, 1):
            b_id = b["id"]
            post_num = b["post_num"]
            title = b["title"]
            date_str = b["date"] or ""
            image_urls = json.loads(b["image_urls"]) if b.get("image_urls") else []
            
            print(f"[{idx}/{len(target_items)}] #{post_num} ({title}) 분석 시작...")
            
            if not image_urls:
                print(f"  [!] 주보 이미지가 없어 건너뜁니다.")
                continue
                
            analysis = crawler.extract_bulletin_info_with_gemini(image_urls, date_str)
            if analysis:
                update_data = {
                    "id": b_id,
                    "post_num": post_num,
                    "title": title,
                    "post_date": b["post_date"],
                    "author": b["author"],
                    "view_count": b["view_count"],
                    "detail_url": b["detail_url"],
                    "image_urls": image_urls,
                    "date": analysis.get("date") or date_str,
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
                success_count += 1
                print(f"  [v] 완료: {update_data['date']} | 설교: {update_data['sermon_title']} | 설교자: {update_data['preacher']}")
            else:
                print(f"  [x] 분석 실패 (다음 작업으로 계속 진행)")
                
            time.sleep(delay)
            
        print(f"\n[*] 자동 분석 완료! (성공: {success_count}건 / 시도: {len(target_items)}건)")
    finally:
        is_running = False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="미분석 주보 자동 일괄 분석기")
    parser.add_argument("--limit", type=int, default=None, help="처리할 개수 (기본: 전체)")
    parser.add_argument("--delay", type=float, default=4.5, help="요청 간 딜레이 초 (기본: 4.5초)")
    args = parser.parse_args()
    
    run_batch_analysis(limit=args.limit, delay=args.delay)
