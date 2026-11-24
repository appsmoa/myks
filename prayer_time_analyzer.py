import os
import requests
import json
import time
import re
from typing import Optional, Dict
from dotenv import load_dotenv

def extract_prayer_timestamp_with_gemini(youtube_url: str, prayer_name: str, worship_type: str = "") -> Optional[int]:
    """
    Gemini 비전/오디오 모델을 사용하여 유튜브 예배 영상에서 대표기도자가 기도를 시작하는 시점(초 단위)을 자동 추출합니다.
    성공 시 시작 초(int, 예: 1523 -> 25분 23초)를 반환하고, 실패 시 None을 반환합니다.
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

    # videoId 추출
    vid_match = re.search(r'(?:v=|\/embed\/|youtu\.be\/)([a-zA-Z0-9_-]{11})', youtube_url)
    if not vid_match:
        return None
    vid = vid_match.group(1)
    clean_video_url = f"https://www.youtube.com/watch?v={vid}"

    clean_name = prayer_name.strip()
    worship_hint = f" ({worship_type} 예배)" if worship_type else ""

    prompt = f"""
당신은 교회 예배 영상 정밀 분석 전문가입니다.
제공된 유튜브 영상은 금성교회{worship_hint} 실시간 스트리밍 녹화 영상입니다.
이 예배의 대표기도자는 [{clean_name}]입니다.

영상에서 예배 전 찬양이 끝나고 강단에 나와 대표기도([{clean_name}])가 시작되는 정확한 시점(타임스탬프)을 찾아주세요.
화면 하단에 [기도 | {clean_name}] 자막이 나타나거나 기도자가 마이크를 잡고 기도를 시작하는 순간(초 단위)입니다.

반드시 다음 JSON 형식으로만 응답해 주세요:
{{
  "prayer_name": "{clean_name}",
  "timestamp_str": "MM:SS",
  "total_seconds": 1523,
  "confidence": "high/medium/low",
  "evidence": "기도 시작 증거 설명"
}}
"""

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

    # 지원되는 고성능 모델 우선순위
    models = ["gemini-3.1-flash-lite", "gemini-3-flash-preview", "gemini-flash-latest"]

    for key_idx, key in enumerate(keys):
        for model in models:
            api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            try:
                print(f"[PrayerAnalyzer] 영상 분석 요청: {clean_name} ({clean_video_url}, {model}, Key #{key_idx + 1})...")
                res = requests.post(api_url, json=payload, headers={"Content-Type": "application/json"}, timeout=30)
                if res.status_code == 200:
                    res_data = res.json()
                    parts = res_data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                    if parts and "text" in parts[0]:
                        parsed = json.loads(parts[0]["text"])
                        secs = parsed.get("total_seconds")
                        if secs and isinstance(secs, (int, float)) and secs > 60:
                            print(f"[PrayerAnalyzer] 성공! [{clean_name}] 기도 시작 시간: {secs}초 ({parsed.get('timestamp_str')})")
                            return int(secs)
                elif res.status_code == 503:
                    time.sleep(1)
                    continue
                else:
                    print(f"[PrayerAnalyzer] API 응답 {res.status_code}: {res.text[:120]}")
            except Exception as e:
                print(f"[PrayerAnalyzer Error] {e}")
            time.sleep(1)

    print(f"[PrayerAnalyzer] [{clean_name}] 타임스탬프 추출 실패 (기본 링크 유지)")
    return None

def attach_timestamp_to_youtube_url(url: str, seconds: int) -> str:
    """
    유튜브 URL에 시작 초(&t=1523s)를 붙입니다.
    """
    if not url or not seconds:
        return url
    base_url = re.sub(r'[?&]t=\d+s?', '', url)
    sep = '&' if '?' in base_url else '?'
    return f"{base_url}{sep}t={seconds}s"

def extract_prayer_name_from_servants(servants: dict, worship_type: str) -> Optional[str]:
    """
    주보 servants 딕셔너리에서 9시, 11시, 수요 기도자 성함을 추출합니다.
    """
    if not servants or not isinstance(servants, dict):
        return None

    if worship_type == "9시":
        v = servants.get("9시_예배") or servants.get("1부_예배") or servants.get("9시")
        if isinstance(v, dict):
            return v.get("기도") or v.get("대표기도")
        return servants.get("9시_기도")
    elif worship_type == "11시":
        v = servants.get("11시_예배") or servants.get("2부_예배") or servants.get("11시")
        if isinstance(v, dict):
            return v.get("기도") or v.get("대표기도")
        return servants.get("11시_기도")
    elif worship_type == "수요":
        v = servants.get("수요_예배") or servants.get("수요예배")
        if isinstance(v, dict):
            return v.get("기도") or v.get("대표기도")
        return servants.get("수요_기도") or servants.get("수요기도")
    return None

def enrich_youtube_urls_with_prayer_timestamps(yt_links: dict, servants: dict) -> dict:
    """
    yt_links의 각 예배 영상(9시, 11시, 수요)에 대해 기도자 성함을 찾아
    Gemini AI로 기도 시작 타임스탬프를 추출하여 URL에 &t=...를 부착합니다.
    """
    if not yt_links:
        return {}

    updated = dict(yt_links)
    for w_type in ["11시", "9시", "수요"]:
        url = updated.get(w_type)
        if not url:
            continue
        # 이미 t 파라미터가 있으면 유지
        if re.search(r'[?&]t=\d+s?', url):
            continue

        p_name = extract_prayer_name_from_servants(servants, w_type)
        if p_name:
            secs = extract_prayer_timestamp_with_gemini(url, p_name, w_type)
            if secs:
                updated[w_type] = attach_timestamp_to_youtube_url(url, secs)

    return updated
