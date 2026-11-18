@echo off
chcp 65001 > nul
echo.
echo ==============================================
echo     금성교회 주보 시스템 GitHub 원클릭 배포
echo ==============================================
echo.
echo [1/3] 변경된 모든 파일을 준비합니다 (git add)...
git add .

set /p msg="커밋 설명 입력 (그냥 Enter 치면 '주보 데이터 업데이트'로 등록): "
if "%msg%"=="" set msg=주보 데이터 업데이트

echo.
echo [2/3] 변경사항 저장 중 (git commit)...
git commit -m "%msg%"

echo.
echo [3/3] GitHub로 전송 중 (git push)...
git push origin main

echo.
echo ==============================================
echo [성공] GitHub 업로드 완료! Render 배포가 자동 시작됩니다.
echo ==============================================
echo.
pause
