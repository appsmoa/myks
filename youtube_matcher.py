import re
import json
import time
import requests
from datetime import datetime, timedelta
from typing import Dict, Optional, List

YOUTUBE_STREAMS_URL = "https://www.youtube.com/@Myks478/streams"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
}

# 10분 메모리 캐시
_cached_streams: List[dict] = []
_cache_time: float = 0.0

def fetch_youtube_streams(force_refresh: bool = False) -> List[dict]:
    """
    금성교회 유튜브 라이브 스트림 탭에서 최신 예배 영상 목록을 가져와 파싱합니다.
    """
    global _cached_streams, _cache_time
    now = time.time()
    if not force_refresh and _cached_streams and (now - _cache_time < 600):
        return _cached_streams

    try:
        res = requests.get(YOUTUBE_STREAMS_URL, headers=HEADERS, timeout=12)
        if res.status_code != 200:
            print(f"[YouTube Matcher] HTTP {res.status_code} 실패")
            return _cached_streams

        m = re.search(r'var ytInitialData\s*=\s*({.*?});</script>', res.text)
        if not m:
            print("[YouTube Matcher] ytInitialData를 찾을 수 없습니다.")
            return _cached_streams

        data = json.loads(m.group(1))
        streams = []

        def search_videos(obj):
            if isinstance(obj, dict):
                # 최신 lockupViewModel 구조 지원
                if 'lockupViewModel' in obj:
                    lvm = obj['lockupViewModel']
                    rc = lvm.get('rendererContext', {}).get('commandContext', {}).get('onTap', {}).get('innertubeCommand', {})
                    vid = rc.get('watchEndpoint', {}).get('videoId')
                    title = lvm.get('metadata', {}).get('lockupMetadataViewModel', {}).get('title', {}).get('content', '')
                    if vid and title:
                        streams.append({'videoId': vid, 'title': title})
                # 구버전 VideoRenderer 구조 지원
                elif 'videoId' in obj and 'title' in obj:
                    vid = obj.get('videoId')
                    t = obj.get('title')
                    title = ''
                    if isinstance(t, dict):
                        if 'runs' in t:
                            title = ''.join(x.get('text', '') for x in t['runs'])
                        elif 'simpleText' in t:
                            title = t['simpleText']
                    elif isinstance(t, str):
                        title = t
                    if vid and title:
                        streams.append({'videoId': vid, 'title': title})

                for v in obj.values():
                    search_videos(v)
            elif isinstance(obj, list):
                for item in obj:
                    search_videos(item)

        search_videos(data)

        # 제목에서 날짜(월/일)와 예배 종류(9시, 11시, 수요) 파싱
        parsed = []
        seen_vids = set()
        for s in streams:
            vid = s['videoId']
            if vid in seen_vids:
                continue
            seen_vids.add(vid)

            title = s['title']
            m_date = re.search(r'(\d{1,2})월\s*(\d{1,2})일', title)
            if not m_date:
                continue
            month, day = int(m_date.group(1)), int(m_date.group(2))

            worship_type = None
            if '수요' in title:
                worship_type = '수요'
            elif '11시' in title or '11:00' in title or '2부' in title:
                worship_type = '11시'
            elif '9시' in title or '9:00' in title or '1부' in title:
                worship_type = '9시'
            elif '주일' in title:
                # 11시 언급 없는 주일예배는 통상 1부(9시)
                worship_type = '9시'

            if worship_type:
                parsed.append({
                    'month': month,
                    'day': day,
                    'type': worship_type,
                    'title': title,
                    'videoId': vid,
                    'url': f"https://www.youtube.com/watch?v={vid}"
                })

        _cached_streams = parsed
        _cache_time = now
        print(f"[YouTube Matcher] 성공적으로 {len(parsed)}건의 예배 스트림 영상을 파싱했습니다.")
        return parsed

    except Exception as e:
        print(f"[YouTube Matcher Error] {e}")
        return _cached_streams

def get_youtube_links_for_bulletin(bulletin_date_str: str) -> Dict[str, str]:
    """
    주보 날짜 (YYYY-MM-DD 또는 YYYY.MM.DD)에 매칭되는 9시, 11시, 수요예배 유튜브 링크를 찾습니다.
    반환 예시:
    {
        "9시": "https://www.youtube.com/watch?v=...",
        "11시": "https://www.youtube.com/watch?v=...",
        "수요": "https://www.youtube.com/watch?v=..."
    }
    """
    if not bulletin_date_str:
        return {}

    clean_date = bulletin_date_str.replace('.', '-').strip()
    match = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', clean_date)
    if not match:
        return {}

    try:
        y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
        dt = datetime(y, m, d)
    except Exception:
        return {}

    streams = fetch_youtube_streams()
    if not streams:
        return {}

    # 주일 기준 직전 수요일 계산 (일요일이면 -4일)
    # weekday(): 월요일 0, 화 1, 수 2, 목 3, 금 4, 토 5, 일 6
    weekday = dt.weekday()
    if weekday == 6: # 일요일
        wed_dt = dt - timedelta(days=4)
    else:
        # 혹시 일요일이 아닌 경우 가장 가까운 수요일
        wed_dt = dt - timedelta(days=(weekday - 2) % 7)

    wm, wd = wed_dt.month, wed_dt.day

    results = {}

    # 1. 9시 예배
    item_9 = next((x for x in streams if x['month'] == m and x['day'] == d and x['type'] == '9시'), None)
    if item_9:
        results['9시'] = item_9['url']

    # 2. 11시 예배
    item_11 = next((x for x in streams if x['month'] == m and x['day'] == d and x['type'] == '11시'), None)
    if item_11:
        results['11시'] = item_11['url']

    # 3. 수요 예배 (직전 수요일 우선, 또는 주일 기준 4일 이내 수요일)
    item_wed = next((x for x in streams if x['month'] == wm and x['day'] == wd and x['type'] == '수요'), None)
    if not item_wed:
        item_wed = next((x for x in streams if x['month'] == m and abs(x['day'] - d) <= 4 and x['type'] == '수요'), None)
    if item_wed:
        results['수요'] = item_wed['url']

    return results

if __name__ == "__main__":
    test_dates = ["2026-11-22", "2026-11-15", "2026-11-08"]
    for t_date in test_dates:
        links = get_youtube_links_for_bulletin(t_date)
        print(f"{t_date} -> {links}")
