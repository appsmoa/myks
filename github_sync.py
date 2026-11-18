import os
import base64
import requests
from dotenv import load_dotenv

load_dotenv()

REPO_OWNER = os.getenv("GITHUB_REPO_OWNER", "appsmoa")
REPO_NAME = os.getenv("GITHUB_REPO_NAME", "myks")
BRANCH = os.getenv("GITHUB_BRANCH", "main")
FILE_PATH = "bulletin.db"

def sync_db_to_github() -> dict:
    """
    최신 bulletin.db 파일을 GitHub API를 통해 appsmoa/myks 저장소로 자동 커밋 & 푸시합니다.
    GITHUB_TOKEN (또는 GITHUB_PAT) 환경변수가 필요합니다.
    """
    token = os.getenv("GITHUB_TOKEN", "").strip() or os.getenv("GITHUB_PAT", "").strip()
    if not token:
        print("[GitHub Sync] GITHUB_TOKEN이 설정되어 있지 않아 GitHub 자동 저장을 건너뜁니다.")
        return {"success": False, "message": "GITHUB_TOKEN 환경변수가 설정되지 않았습니다."}

    db_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), FILE_PATH)
    if not os.path.exists(db_file):
        return {"success": False, "message": "bulletin.db 파일을 찾을 수 없습니다."}

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"

    # 1. 기존 파일의 sha 값 조회
    sha = None
    try:
        get_res = requests.get(url, headers=headers, params={"ref": BRANCH}, timeout=10)
        if get_res.status_code == 200:
            sha = get_res.json().get("sha")
        elif get_res.status_code == 404:
            sha = None # 새 파일
        else:
            return {"success": False, "message": f"GitHub 파일 정보 조회 실패: {get_res.status_code} {get_res.text}"}
    except Exception as e:
        return {"success": False, "message": f"GitHub 통신 오류: {str(e)}"}

    # 2. bulletin.db 바이너리 base64 인코딩
    try:
        with open(db_file, "rb") as f:
            content_bytes = f.read()
            encoded_content = base64.b64encode(content_bytes).decode("utf-8")
    except Exception as e:
        return {"success": False, "message": f"DB 파일 읽기 실패: {str(e)}"}

    # 3. GitHub API를 통해 새 커밋 전송 (PUT)
    payload = {
        "message": "자동 동기화: 최신 주보 bulletin.db 자동 갱신",
        "content": encoded_content,
        "branch": BRANCH
    }
    if sha:
        payload["sha"] = sha

    try:
        put_res = requests.put(url, headers=headers, json=payload, timeout=30)
        if put_res.status_code in [200, 201]:
            commit_info = put_res.json()
            commit_sha = commit_info.get("commit", {}).get("sha", "")[:7]
            print(f"[GitHub Sync] bulletin.db가 GitHub로 성공적으로 자동 커밋되었습니다! (Commit: {commit_sha})")
            return {"success": True, "message": f"GitHub 저장소로 DB가 자동 저장되었습니다! (커밋 #{commit_sha})", "commit": commit_sha}
        else:
            return {"success": False, "message": f"GitHub 커밋 실패: {put_res.status_code} {put_res.text}"}
    except Exception as e:
        return {"success": False, "message": f"GitHub 커밋 중 오류: {str(e)}"}
