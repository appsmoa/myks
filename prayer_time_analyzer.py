import os
import requests
import json
import time
import re
from typing import Optional, Dict
from dotenv import load_dotenv

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

def extract_prayer_timestamp_with_gemini(youtube_url: str, prayer_name: str, worship_type: str = "") -> Optional[int]:
    """
    Gemini 비전/오디오 모델을 사용하여 유튜브 예배 영상에서 대표기도자가 기도를 시작하는 시점(초 단위)을 자동 추출합니다.
    """
    if not youtube_url or not prayer_name:
        return None

    # 이미 타임스탬프가 포함되어 있는 경우 기존 초 반환
    m_t = re.search(r'[?&]t=(\d+)s?', youtube_url)
    if m_t:
        return int(m_t.group(1))

    load_dotenv(override=True)
    api_key_str = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key_str:
        print("[PrayerAnalyzer] GEMINI_API_KEY가 설정되지 않았습니다.")
        return None

    keys = [k.strip() for k in api_key_str.replace('\n', ',').split(',') if k.strip()]
    if not keys:
        return None

    vid_match = re.search(r'(?:v=|\/embed\/|youtu\.be\/)([a-zA-Z0-9_-]{11})', youtube_url)
    if not vid_match:
        return None
    vid = vid_match.group(1)
    clean_video_url = f"https://www.youtube.com/watch?v={vid}"

    clean_name = prayer_name.strip()
    worship_hint = f" ({worship_type} 예배)" if worship_type else ""

    # 1차 정밀 탐색 프롬프트
    prompt_primary = f"""
당신은 교회 예배 영상 정밀 분석 전문가입니다.
제공된 유튜브 영상은 금성교회{worship_hint} 실시간 스트리밍 녹화 영상입니다.
이 예배의 대표기도자는 [{clean_name}]입니다.

영상에서 예배 전 찬양이 끝나고 강단에 나와 대표기도([{clean_name}])가 시작되는 정확한 시점(타임스탬프)을 찾아주세요.
화면 하단에 [기도 | {clean_name}] 자막이 나타나거나 기도자가 마이크를 잡고 기도를 시작하는 순간(초 단위)입니다.
일반적으로 찬양 후 15분~28분 사이에 위치합니다.

반드시 다음 JSON 형식으로만 응답해 주세요:
{{
  "prayer_name": "{clean_name}",
  "timestamp_str": "MM:SS",
  "total_seconds": 1363,
  "confidence": "high/medium/low",
  "evidence": "기도 시작 증거 설명"
}}
"""

    # 2차 유연 탐색 프롬프트 (이름 자막 매칭이 애매할 때 회중 대표기도 식별)
    prompt_secondary = f"""
제공된 유튜브 영상({clean_video_url})은 금성교회{worship_hint} 예배 실시간 녹화 영상입니다.
영상에서 시작 찬양팀 찬양이 끝나고, 인도자의 멘트 후 대표기도자가 강단에 올라와 마이크를 잡고 회중을 대표하여 기도를 시작하는 시점(MM:SS)을 찾아주세요.
보통 15분~28분 사이에 위치합니다.

JSON으로만 응답해 주세요:
{{
  "prayer_name": "{clean_name}",
  "timestamp_str": "MM:SS",
  "total_seconds": 1363
}}
"""

    def parse_seconds_flexible(data: dict) -> Optional[int]:
        if not isinstance(data, dict):
            return None
        # 1. total_seconds 필드 검사
        secs = data.get("total_seconds")
        if secs is not None:
            try:
                s_clean = re.sub(r'[^\d.]', '', str(secs))
                if s_clean:
                    v = int(float(s_clean))
                    if v > 60:
                        return v
            except:
                pass
        # 2. timestamp_str (MM:SS, HH:MM:SS, XX분 YY초) 파싱
        ts = str(data.get("timestamp_str") or "")
        if ts:
            m = re.search(r'(?:(\d{1,2}):)?(\d{1,2}):(\d{2})', ts)
            if m:
                h = int(m.group(1)) if m.group(1) else 0
                m_v = int(m.group(2))
                s_v = int(m.group(3))
                tot = h * 3600 + m_v * 60 + s_v
                if tot > 60:
                    return tot
            m_kor = re.search(r'(?:(\d+)시간\s*)?(?:(\d+)분\s*)?(\d+)초', ts)
            if m_kor:
                h = int(m_kor.group(1)) if m_kor.group(1) else 0
                m_v = int(m_kor.group(2)) if m_kor.group(2) else 0
                s_v = int(m_kor.group(3)) if m_kor.group(3) else 0
                tot = h * 3600 + m_v * 60 + s_v
                if tot > 60:
                    return tot
        return None

    models = ["gemini-3.1-flash-lite", "gemini-3-flash-preview"]
    num_keys = len(keys)
    start_key_idx = 0
    if worship_type == "9시": start_key_idx = 1
    elif worship_type == "수요": start_key_idx = 2
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
                try:
                    print(f"[PrayerAnalyzer] 영상 분석 요청({attempt}차): {clean_name} ({clean_video_url}, {model}, Key #{key_idx + 1})...")
                    res = requests.post(api_url, json=payload, headers={"Content-Type": "application/json"}, timeout=65)
                    if res.status_code == 200:
                        res_data = res.json()
                        parts = res_data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                        if parts and "text" in parts[0]:
                            parsed = json.loads(parts[0]["text"])
                            secs = parse_seconds_flexible(parsed)
                            if secs:
                                print(f"[PrayerAnalyzer] 성공! [{clean_name}] 기도 시작 시간: {secs}초 ({secs//60:02d}:{secs%60:02d})")
                                return secs
                    elif res.status_code in (429, 503):
                        print(f"[PrayerAnalyzer] 일시적 부하 ({res.status_code}), 다음 키로 교체 재시도...")
                        time.sleep(2)
                        continue
                    else:
                        print(f"[PrayerAnalyzer] API 응답 {res.status_code}: {res.text[:100]}")
                except Exception as e:
                    print(f"[PrayerAnalyzer Error] {e}")
                time.sleep(1)

    print(f"[PrayerAnalyzer] [{clean_name}] 타임스탬프 추출 실패 (기본 링크 유지)")
    return None

def attach_timestamp_to_youtube_url(url: str, seconds: int) -> str:
    if not url or not seconds:
        return url
    base_url = re.sub(r'[?&]t=\d+s?', '', url)
    sep = '&' if '?' in base_url else '?'
    return f"{base_url}{sep}t={seconds}s"

from concurrent.futures import ThreadPoolExecutor

def enrich_youtube_urls_with_prayer_timestamps(yt_links: dict, servants: dict) -> dict:
    if not yt_links:
        return {}

    updated = dict(yt_links)
    tasks = []
    worship_priority = ["11시", "9시", "수요"]
    for w_type in worship_priority:
        url = updated.get(w_type)
        if not url:
            continue
        if re.search(r'[?&]t=\d+s?', url):
            continue

        p_name = extract_prayer_name_from_servants(servants, w_type)
        if p_name:
            tasks.append((w_type, url, p_name))

    if not tasks:
        return updated

    def analyze_one(item):
        w_type, url, p_name = item
        secs = extract_prayer_timestamp_with_gemini(url, p_name, w_type)
        return w_type, url, secs

    # 11시, 9시, 수요 영상을 서로 다른 키로 동시 병렬 분석!
    with ThreadPoolExecutor(max_workers=min(len(tasks), 3)) as executor:
        results = executor.map(analyze_one, tasks)
        for w_type, url, secs in results:
            if secs:
                updated[w_type] = attach_timestamp_to_youtube_url(url, secs)

    return updated
