#!/bin/sh
# 최신 스코어·레이팅 받기 → 시뮬레이션 → 대시보드 생성 → 페이지 스크립트 문법 검사
cd "$(dirname "$0")" && python -X utf8 fetch_data.py && python -X utf8 ucl_model.py && python -X utf8 build_dashboard.py || exit 1
python -X utf8 -c "s=open('dashboard.html',encoding='utf-8').read();open('out/page.js','w',encoding='utf-8').write(s[s.rfind('<script>')+8:s.rfind('</script>')])"
node --check out/page.js && echo "페이지 스크립트 OK" || { echo "페이지 스크립트 오류 — 게시하지 말 것"; exit 1; }
