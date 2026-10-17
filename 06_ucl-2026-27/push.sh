#!/bin/sh
# 로컬에서 고친 부상 정보(data/injuries.csv)만 올리고, 나머지(점수·시뮬레이션·페이지)는 GitHub Actions가 다시 만들게 함.
# 생성 파일까지 로컬에서 올리면 10분마다 도는 Actions 커밋과 충돌하기 때문.
cd "$(dirname "$0")" || exit 1
git add data/injuries.csv
if git diff --cached --quiet; then echo "GitHub: 부상 정보 변경 없음"; git checkout -q -- . ; git pull -q --rebase; exit 0; fi
git commit -q -m "UCL 부상 정보 갱신 $(TZ=KST-9 date '+%Y-%m-%d %H:%M') KST" || exit 1
git checkout -q -- .                 # 로컬 생성 파일은 버림 (Actions가 다시 만듦)
git pull -q --rebase origin main && git push -q origin HEAD:main || exit 1
gh workflow run ucl-update.yml -f mode=full >/dev/null && echo "GitHub: 부상 정보 push, 전체 갱신 실행 요청"
