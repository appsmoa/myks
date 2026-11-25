import os
import requests
import json
import time
import re
from typing import Optional, Dict
from dotenv import load_dotenv
from database import get_gemini_api_keys

def extract_prayer_name_from_servants(servants: dict, worship_type: str) -> Optional[str]:
    """
    주보 servants 딕셔너리의 다양한 중첩 구조에서 9시, 11시, 수요 기도자 성함을 완벽하게 추출합니다.
    지원 패턴:
    1. {"9시_기도": "이름", "11시_기도": "이름"}
    2. {"대표기도": {"9시예배": "이름", "11시예배": "이름", "수요찬양기도회": "이름"}}
    3. {"9시_예배": {"기도": "이름"}, "11시_예배": {"기도": "이름"}}
    4. {"기도": {"9시": "이름", "11시": "이름", "수요": "이름"}}
    5. 문자열 전체 검색
    """
    if not servants:
        return None

    if isinstance(servants, str):
        try:
            servants = json.loads(servants)
        except Exception:
            pass

    if not isinstance(servants, dict):
        return None

    # 패턴 1: 직접 키 (예: 9시_기도, 11시_기도, 수요_기도)
    if worship_type == "9시":
        for k in ["9시_기도", "9시기도", "1부_기도", "1부기도"]:
            if servants.get(k) and isinstance(servants[k], str):
                return servants[k].strip()
    elif worship_type == "11시":
        for k in ["11시_기도", "11시기도", "2부_기도", "2부기도"]:
            if servants.get(k) and isinstance(servants[k], str):
                return servants[k].strip()
    elif worship_type == "수요":
        for k in ["수요_기도", "수요기도", "수요찬양_기도"]:
            if servants.get(k) and isinstance(servants[k], str):
                return servants[k].strip()

    # 패턴 2: 대표기도 하위 딕셔너리 (예: {"대표기도": {"9시예배": "...", "11시예배": "..."}})
    rep_prayer = servants.get("대표기도") or servants.get("기도")
    if isinstance(rep_prayer, dict):
        for k, v in rep_prayer.items():
            if isinstance(v, str):
                if worship_type == "9시" and any(x in k for x in ["9시", "1부"]):
                    return v.strip()
                elif worship_type == "11시" and any(x in k for x in ["11시", "2부"]):
                    return v.strip()
                elif worship_type == "수요" and "수요" in k:
                    return v.strip()

    # 패턴 3: 예배별 하위 딕셔너리 (예: {"9시_예배": {"기도": "..."}})
    for w_key in servants.keys():
        w_val = servants[w_key]
        if isinstance(w_val, dict):
            p_val = w_val.get("기도") or w_val.get("대표기도")
            if p_val and isinstance(p_val, str):
                if worship_type == "9시" and any(x in w_key for x in ["9시", "1부"]):
                    return p_val.strip()
                elif worship_type == "11시" and any(x in w_key for x in ["11시", "2부"]):
                    return p_val.strip()
                elif worship_type == "수요" and "수요" in w_key:
                    return p_val.strip()

    return None

def parse_field_seconds(data: dict, prefix: str) -> Optional[int]:
    """Gemini 응답 JSON에서 특정 접두사(prayer 또는 sermon)의 초 단위 타임스탬프를 유연하게 추출"""
    if not isinstance(data, dict):
        return None

    # 1. {prefix}_seconds 또는 total_seconds 필드 검사
    val = data.get(f"{prefix}_seconds")
    if val is None and prefix == "prayer":
        val = data.get("total_seconds")
    if val is not None:
        try:
            s_clean = re.sub(r'[^\d.]', '', str(val))
            if s_clean:
                v = int(float(s_clean))
                if v > 60:
                    return v
        except Exception:
            pass

    # 2. {prefix}_timestamp_str 또는 timestamp_str 필드 파싱
    ts = str(data.get(f"{prefix}_timestamp_str") or (data.get("timestamp_str") if prefix == "prayer" else "") or "")
    if ts:
        # HH:MM:SS 또는 MM:SS
        m = re.search(r'(?:(\d{1,2}):)?(\d{1,2}):(\d{2})', ts)
        if m:
            h = int(m.group(1)) if m.group(1) else 0
            m_v = int(m.group(2))
            s_v = int(m.group(3))
            tot = h * 3600 + m_v * 60 + s_v
            if tot > 60:
                return tot
        
        # XX시간 YY분 ZZ초
        m_kor = re.search(r'(?:(\d+)시간\s*)?(?:(\d+)분\s*)?(\d+)초', ts)
        if m_kor:
            h = int(m_kor.group(1)) if m_kor.group(1) else 0
            m_v = int(m_kor.group(2)) if m_kor.group(2) else 0
            s_v = int(m_kor.group(3)) if m_kor.group(3) else 0
            tot = h * 3600 + m_v * 60 + s_v
            if tot > 60:
                return tot

    return None

def extract_worship_timestamps_with_gemini(
    youtube_url: str, 
    prayer_name: str, 
    sermon_title: str = "", 
    preacher: str = "", 
    worship_type: str = "", 
    start_key_idx: int = 0,
    status_callback = None
) -> dict:
    """
    Gemini 1.5/2.0 API의 비디오 이해 기능을 통해
    YouTube 예배 영상에서 [대표기도 시작 시점]과 [설교 말씀 시작 시점]을
    동시에 단 한 번의 호출로 추출합니다.
    반환: {"prayer_seconds": int|None, "sermon_seconds": int|None}
    """
    res_dict = {"prayer_seconds": None, "sermon_seconds": None}
    if not youtube_url:
        return res_dict

    load_dotenv(override=True)
    api_key_str = get_gemini_api_keys()
    if not api_key_str:
        print("[WorshipAnalyzer] GEMINI_API_KEY가 설정되지 않았습니다.")
        if status_callback:
            status_callback("❌ Gemini API 키가 설정되지 않았습니다.")
        return res_dict

    keys = [k.strip() for k in api_key_str.replace('\n', ',').split(',') if k.strip()]
    if not keys:
        if status_callback:
            status_callback("❌ 등록된 유효한 Gemini API 키가 없습니다.")
        return res_dict

    vid_match = re.search(r'(?:v=|\/embed\/|youtu\.be\/)([a-zA-Z0-9_-]{11})', youtube_url)
    if not vid_match:
        return res_dict
    vid = vid_match.group(1)
    clean_video_url = f"https://www.youtube.com/watch?v={vid}"

    clean_prayer = prayer_name.strip() if prayer_name else "대표기도자"
    clean_sermon = sermon_title.strip() if sermon_title else "주일 설교"
    clean_preacher = preacher.strip() if preacher else "담임목사"
    worship_hint = f" ({worship_type} 예배)" if worship_type else ""

    if status_callback:
        status_callback(f"유튜브 {worship_type} 영상 분석 중... (Gemini 3.1 Flash Lite)")

    prompt_primary = f"""
당신은 교회 예배 영상 정밀 분석 전문가입니다.
제공된 유튜브 영상은 금성교회{worship_hint} 실시간 스트리밍 녹화 영상입니다.
이 예배의 정보:
- 대표기도자: [{clean_prayer}]
- 설교자: [{clean_preacher}]
- 설교 제목: [{clean_sermon}]

영상 전체를 스캔하여 다음 두 구간의 정확한 시작 시점(타임스탬프)을 찾아주세요:

1. [대표기도]: 예배 전 찬양이 끝나고 강단에 나와 대표기도([{clean_prayer}])가 시작되는 순간 (보통 15분~28분 사이)
2. [설교 말씀]: 성가대 찬양 후 목사님([{clean_preacher}])이 강단에 올라와 설교 말씀([{clean_sermon}])을 시작하는 순간 (보통 28분~45분 사이)

반드시 다음 JSON 형식으로만 응답해 주세요:
{{
  "prayer_seconds": 1123,
  "prayer_timestamp_str": "18:43",
  "sermon_seconds": 2055,
  "sermon_timestamp_str": "34:15",
  "sermon_evidence": "설교 시작 부분 설명"
}}
"""

    prompt_secondary = f"""
제공된 유튜브 영상({clean_video_url})은 금성교회{worship_hint} 예배 실시간 녹화 영상입니다.
영상에서:
1. 대표기도자가 강단에 올라와 기도를 시작하는 시점 (MM:SS) (보통 15분~28분)
2. 성가대 찬양 후 목사님이 강단에 서서 설교 말씀을 시작하는 시점 (MM:SS) (보통 28분~45분)

JSON으로 응답해 주세요:
{{
  "prayer_timestamp_str": "18:43",
  "prayer_seconds": 1123,
  "sermon_timestamp_str": "34:15",
  "sermon_seconds": 2055
}}
"""

    models = ["gemini-3.1-flash-lite", "gemini-3-flash-preview"]
    num_keys = len(keys)
    ordered_keys = [keys[(start_key_idx + i) % num_keys] for i in range(num_keys)]

    for attempt, prompt in enumerate([prompt_primary, prompt_secondary], 1):
        payload = {
            "contents": [{
                "parts": [
                    {
                        "fileData": {
                            "mimeType": "video/*",
                            "fileUri": clean_video_url
                        }
                    },
                    {
                        "text": prompt
                    }
                ]
            }],
            "generationConfig": {
                "response_mime_type": "application/json"
            }
        }

        for key_idx, key in enumerate(ordered_keys):
            for model in models:
                api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
                model_display = "Gemini 3.1 Flash Lite" if "flash-lite" in model else "Gemini 3.8 Flash"
                key_display = f"Key #{key_idx + 1}"
                
                if status_callback:
                    status_callback(f"[{model_display} · {key_display}] {worship_type} 예배 영상 타임스탬프 분석 중...")

                try:
                    print(f"[WorshipAnalyzer] 영상 분석 요청({attempt}차): {worship_type} [{clean_prayer}/{clean_sermon}] ({clean_video_url}, {model}, {key_display})...")
                    res = requests.post(api_url, json=payload, headers={"Content-Type": "application/json"}, timeout=65)
                    if res.status_code == 200:
                        res_data = res.json()
                        parts = res_data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                        if parts and "text" in parts[0]:
                            parsed = json.loads(parts[0]["text"])
                            p_sec = parse_field_seconds(parsed, "prayer")
                            s_sec = parse_field_seconds(parsed, "sermon")
                            if p_sec or s_sec:
                                print(f"[WorshipAnalyzer] 성공! [{worship_type}] 기도: {p_sec}초 | 설교: {s_sec}초")
                                res_dict["prayer_seconds"] = p_sec
                                res_dict["sermon_seconds"] = s_sec
                                if status_callback:
                                    status_callback(f"✨ [{model_display}] {worship_type} 예배 타임스탬프 탐색 성공")
                                return res_dict
                    elif res.status_code == 429:
                        msg = f"⚠️ [{model_display} · {key_display}] Google 분당 한도(TPM 250K) 도달: 다음 키 전환 및 쿨타임 대기 중... ({worship_type} 예배)"
                        print(f"[WorshipAnalyzer] {msg}")
                        if status_callback:
                            status_callback(msg)
                        time.sleep(3)
                        continue
                    elif res.status_code == 503:
                        msg = f"⚠️ [{model_display}] 구글 서버 일시 과부하(503): 잠시 대기 후 자동 재시도 중... ({worship_type} 예배)"
                        print(f"[WorshipAnalyzer] {msg}")
                        if status_callback:
                            status_callback(msg)
                        time.sleep(2)
                        continue
                    else:
                        print(f"[WorshipAnalyzer] API 응답 {res.status_code}: {res.text[:100]}")
                except Exception as e:
                    print(f"[WorshipAnalyzer Error] {e}")
                time.sleep(1)

    return res_dict

def extract_prayer_timestamp_with_gemini(youtube_url: str, prayer_name: str, worship_type: str = "", start_key_idx: int = 0) -> Optional[int]:
    """기존 단일 기도 타임스탬프 추출 호환 함수"""
    res = extract_worship_timestamps_with_gemini(youtube_url, prayer_name, worship_type=worship_type, start_key_idx=start_key_idx)
    return res.get("prayer_seconds")

def attach_timestamp_to_youtube_url(url: str, seconds: int) -> str:
    if not url or not seconds:
        return url
    base_url = re.sub(r'[?&]t=\d+s?', '', url)
    sep = '&' if '?' in base_url else '?'
    return f"{base_url}{sep}t={seconds}s"

from concurrent.futures import ThreadPoolExecutor
import threading

def enrich_youtube_urls_with_prayer_and_sermon_timestamps(
    yt_links: dict, 
    servants: dict, 
    sermon_title: str = "", 
    preacher: str = "",
    status_callback = None
) -> tuple:
    """
    유튜브 영상 링크 딕셔너리를 입력받아,
    기도 타임스탬프가 적용된 youtube_urls 와
    설교 말씀 타임스탬프가 적용된 youtube_sermon_urls 를 동시에 반환합니다.
    """
    if not yt_links:
        return {}, {}

    prayer_urls = dict(yt_links)
    sermon_urls = dict(yt_links)
    tasks = []
    worship_priority = ["11시", "9시", "수요"]

    for idx, w_type in enumerate(worship_priority):
        url = yt_links.get(w_type)
        if not url:
            continue

        p_name = extract_prayer_name_from_servants(servants, w_type)
        tasks.append((idx, w_type, url, p_name))

    if not tasks:
        return prayer_urls, sermon_urls

    cb_lock = threading.Lock()
    def safe_callback(msg: str):
        if status_callback:
            with cb_lock:
                status_callback(msg)

    def analyze_one(item):
        key_slot, w_type, url, p_name = item
        timestamps = extract_worship_timestamps_with_gemini(
            url, 
            p_name, 
            sermon_title=sermon_title, 
            preacher=preacher, 
            worship_type=w_type, 
            start_key_idx=key_slot,
            status_callback=safe_callback
        )
        return w_type, url, timestamps

    # 11시, 9시, 수요 영상을 서로 다른 키로 동시 병렬 분석!
    with ThreadPoolExecutor(max_workers=min(len(tasks), 3)) as executor:
        results = executor.map(analyze_one, tasks)
        for w_type, url, ts in results:
            p_sec = ts.get("prayer_seconds")
            s_sec = ts.get("sermon_seconds")
            if p_sec:
                prayer_urls[w_type] = attach_timestamp_to_youtube_url(url, p_sec)
            if s_sec:
                sermon_urls[w_type] = attach_timestamp_to_youtube_url(url, s_sec)

    return prayer_urls, sermon_urls

def enrich_youtube_urls_with_prayer_timestamps(yt_links: dict, servants: dict) -> dict:
    """하위 호환성을 위한 래퍼 함수"""
    p_urls, _ = enrich_youtube_urls_with_prayer_and_sermon_timestamps(yt_links, servants)
    return p_urls
