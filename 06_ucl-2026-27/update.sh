#!/bin/sh
# sh update.sh       빠른 갱신: 스코어·레이팅 → 시뮬레이션 → 페이지 (경기 중에 씀)
# sh update.sh full  전체 갱신: 위 + 상대전적·이동거리·휴식일·날씨 다시 모으기
cd "$(dirname "$0")" || exit 1
python -X utf8 fetch_data.py || exit 1
if [ "$1" = "full" ]; then
  python -X utf8 factors.py || exit 1   # 팀별 홈 이점(home_advantage.py)은 거의 안 변해 따로 가끔 돌림
fi
python -X utf8 ucl_model.py && python -X utf8 build_dashboard.py || exit 1
python -X utf8 -c "s=open('dashboard.html',encoding='utf-8').read();open('out/page.js','w',encoding='utf-8').write(s[s.rfind('<script>')+8:s.rfind('</script>')])"
node --check out/page.js && echo "페이지 스크립트 OK" || { echo "페이지 스크립트 오류 — 게시하지 말 것"; exit 1; }
