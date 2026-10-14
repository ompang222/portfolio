#!/bin/sh
# 갱신된 06_ucl-2026-27 폴더만 커밋해 GitHub(Pages)에 올림. 바뀐 게 없으면 아무것도 안 함
cd "$(dirname "$0")" || exit 1
git add -A . && git diff --cached --quiet && { echo "GitHub: 변경 없음"; exit 0; }
git commit -q -m "UCL 대시보드 갱신 $(TZ=Asia/Seoul date '+%Y-%m-%d %H:%M') KST

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git push -q origin main && echo "GitHub: push 완료 $(git log --oneline -1)"
