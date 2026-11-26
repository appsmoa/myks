import re
import json
import time
import requests
import os
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Optional, List

YOUTUBE_STREAMS_URL = "https://www.youtube.com/@Myks478/streams"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
}

# 10분 메모리 캐시 및 전체 과거 스트림 사전 로드
_cached_streams: List[dict] = []
_cache_time: float = 0.0

HISTORY_FILE = "youtube_all_streams.json"
_history_loaded = False

def resolve_stream_types(streams: List[dict]) -> List[dict]:
    """
    유튜브 영상 목록(최신순 정렬)을 분석하여 예배 종류(9시, 11시, 수요)를 정밀 추론합니다.
    - 제목에 '9시', '11시', '수요'가 명시되어 있으면 우선 반영합니다.
    - 동일 주일에 영상이 2개 올라오는 경우 상호 보완 추론:
      * 한 영상이 '9시 예배'이고 다른 영상이 시간 표시가 없는 '주일예배'인 경우 -> 다른 영상은 '11시'
      * 한 영상이 '11시 예배'이고 다른 영상이 시간 표시가 없는 '주일예배'인 경우 -> 다른 영상은 '9시'
      * 둘 다 시간 표시가 없는 경우 -> 먼저 스트리밍된 뒤쪽 영상이 '9시', 나중에 스트리밍된 앞쪽 영상이 '11시'
      * 1개만 있는 일반 주일예배 -> '11시'
    """
    for s in streams:
        t = s.get('title', '')
        if '수요' in t:
            s['inferred_type'] = '수요'
        elif any(k in t for k in ['11시', '11:00', '2부']):
            s['inferred_type'] = '11시'
        elif any(k in t for k in ['9시', '9:00', '1부']):
            s['inferred_type'] = '9시'
        elif any(k in t for k in ['주일', '부활절', '성탄', '송구영신', '신년', '예배']):
            s['inferred_type'] = '주일_미정'
        else:
            s['inferred_type'] = '기타'

    # (year, month, day) 별 그룹핑
    by_date = defaultdict(list)
    for s in streams:
        by_date[(s.get('year'), s.get('month'), s.get('day'))].append(s)

    for (y, m, d), vlist in by_date.items():
        sunday_vids = [v for v in vlist if v['inferred_type'] in ['9시', '11시', '주일_미정']]
        
        has_explicit_9 = any(v['inferred_type'] == '9시' for v in sunday_vids)
        has_explicit_11 = any(v['inferred_type'] == '11시' for v in sunday_vids)
        unresolved = [v for v in sunday_vids if v['inferred_type'] == '주일_미정']

        if has_explicit_9 and not has_explicit_11:
            # 9시가 있고 11시가 없으면, 미정 영상 중 가장 앞(최신 스트림) 영상을 11시로 할당
            if unresolved:
                unresolved[0]['inferred_type'] = '11시'
        elif has_explicit_11 and not has_explicit_9:
            # 11시가 있고 9시가 없으면, 미정 영상 중 가장 뒤(이전 스트림) 영상을 9시로 할당
            if unresolved:
                unresolved[-1]['inferred_type'] = '9시'
        elif not has_explicit_9 and not has_explicit_11:
            if len(unresolved) >= 2:
                # 앞쪽(최신, 늦게 끝남) = 11시, 뒤쪽(이전, 일찍 시작) = 9시
                unresolved[0]['inferred_type'] = '11시'
                unresolved[1]['inferred_type'] = '9시'
            elif len(unresolved) == 1:
                # 1개만 있으면 통상 본예배인 11시
                unresolved[0]['inferred_type'] = '11시'

    for s in streams:
        if s.get('inferred_type') in ['9시', '11시', '수요']:
            s['type'] = s['inferred_type']

    return streams

def _load_history_streams():
    global _cached_streams, _history_loaded
    if _history_loaded:
        return
    file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), HISTORY_FILE)
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw_streams = json.load(f)
                _cached_streams = resolve_stream_types(raw_streams)
                _history_loaded = True
                print(f"[YouTube Matcher] 과거 전체 스트림 {len(_cached_streams)}건 로드 및 추론 완료!")
        except Exception as e:
            print(f"[YouTube Matcher] 과거 스트림 로드 오류: {e}")

_load_history_streams()

def fetch_youtube_streams(force_refresh: bool = False) -> List[dict]:
    """
    금성교회 유튜브 라이브 스트림 탭에서 최신 예배 영상 목록을 가져와 기존 목록과 병합 및 재추론합니다.
    """
    global _cached_streams, _cache_time
    _load_history_streams()
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
                if 'lockupViewModel' in obj:
                    lvm = obj['lockupViewModel']
                    rc = lvm.get('rendererContext', {}).get('commandContext', {}).get('onTap', {}).get('innertubeCommand', {})
                    vid = rc.get('watchEndpoint', {}).get('videoId')
                    title = lvm.get('metadata', {}).get('lockupMetadataViewModel', {}).get('title', {}).get('content', '')
                    if vid and title:
                        streams.append({'videoId': vid, 'title': title})
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
                return
            elif isinstance(obj, list):
                for item in obj:
                    search_videos(item)

        search_videos(data)

        # 최신 스트림 파싱
        parsed = []
        seen_vids = set()
        curr_year = datetime.now().year
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

            parsed.append({
                'date': f"{curr_year}-{month:02d}-{day:02d}",
                'year': curr_year,
                'month': month,
                'day': day,
                'title': title,
                'videoId': vid,
                'url': f"https://www.youtube.com/watch?v={vid}"
            })

        # 기존 과거 전체 캐시와 최신 스트림 병합 (최신순 유지)
        existing_vids = {x['videoId'] for x in _cached_streams}
        new_items = [x for x in parsed if x['videoId'] not in existing_vids]
        combined = new_items + _cached_streams
        _cached_streams = resolve_stream_types(combined)
        _cache_time = now
        print(f"[YouTube Matcher] 성공적으로 최신 {len(new_items)}건 추가, 총 {len(_cached_streams)}건 유지 중.")
        
        if new_items:
            try:
                hist_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), HISTORY_FILE)
                with open(hist_path, "w", encoding="utf-8") as f:
                    json.dump(_cached_streams, f, ensure_ascii=False, indent=2)
                print(f"[YouTube Matcher] {len(new_items)}건의 새 스트림을 {HISTORY_FILE}에 영구 저장했습니다.")
            except Exception as se:
                print(f"[YouTube Matcher Save Error] {se}")

        return _cached_streams

    except Exception as e:
        print(f"[YouTube Matcher Error] {e}")
        return _cached_streams

def get_youtube_links_for_bulletin(bulletin_date_str: str) -> Dict[str, str]:
    """
    주보 날짜 (YYYY-MM-DD 또는 YYYY.MM.DD)에 매칭되는 9시, 11시, 수요예배 유튜브 링크를 찾습니다.
    - 주보의 수요예배는 주일(일요일) 직후의 다가오는 수요일(일요일 + 3일) 예배입니다.
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

    # 주보의 수요예배는 주일(일요일) 직후의 다가오는 수요일입니다.
    # 일요일(weekday=6) 기준 +3일 = 수요일
    # 토요일(weekday=5) 기준 +4일 = 수요일
    weekday = dt.weekday()
    if weekday == 6:  # 일요일
        wed_dt = dt + timedelta(days=3)
    elif weekday == 5:  # 토요일
        wed_dt = dt + timedelta(days=4)
    elif weekday <= 2:  # 월~수요일
        wed_dt = dt + timedelta(days=(2 - weekday))
    else:  # 목~금요일
        wed_dt = dt + timedelta(days=(9 - weekday))

    wy, wm, wd = wed_dt.year, wed_dt.month, wed_dt.day

    results = {}

    # 1. 9시 예배
    item_9 = next((x for x in streams if x.get('year') == y and x['month'] == m and x['day'] == d and x.get('type') == '9시'), None)
    if not item_9 and y == 2026:
        item_9 = next((x for x in streams if x['month'] == m and x['day'] == d and x.get('type') == '9시'), None)
    if item_9:
        results['9시'] = item_9['url']

    # 2. 11시 예배
    item_11 = next((x for x in streams if x.get('year') == y and x['month'] == m and x['day'] == d and x.get('type') == '11시'), None)
    if not item_11 and y == 2026:
        item_11 = next((x for x in streams if x['month'] == m and x['day'] == d and x.get('type') == '11시'), None)
    if item_11:
        results['11시'] = item_11['url']

    # 3. 수요 예배 (주일 직후 다가오는 수요일 매칭)
    item_wed = next((x for x in streams if x.get('year') == wy and x['month'] == wm and x['day'] == wd and x.get('type') == '수요'), None)
    if not item_wed and wy == 2026:
        item_wed = next((x for x in streams if x['month'] == wm and x['day'] == wd and x.get('type') == '수요'), None)
    if not item_wed:
        # 수요일 날짜 기준 ±2일 이내의 수요기도회 매칭 (공휴일 등으로 일정이 소폭 조정된 경우)
        def wed_day_diff(x):
            if x.get('type') != '수요':
                return 999
            if x.get('year') and x['year'] != wy:
                return 999
            if x['month'] != wm:
                return 999
            return abs(x['day'] - wd)

        candidates = [x for x in streams if wed_day_diff(x) <= 2]
        if candidates:
            candidates.sort(key=wed_day_diff)
            item_wed = candidates[0]

    if item_wed:
        results['수요'] = item_wed['url']

    return results

if __name__ == "__main__":
    test_dates = ["2026-06-07", "2026-07-19", "2026-11-22", "2026-10-04"]
    for t_date in test_dates:
        links = get_youtube_links_for_bulletin(t_date)
        print(f"{t_date} -> {links}")
