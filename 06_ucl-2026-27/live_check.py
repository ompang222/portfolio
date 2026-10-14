"""GitHub Actions가 이번 실행에서 무엇을 할지 정한다 → 'live' / 'full' / 'skip' 출력.

live: 킥오프 20분 전 ~ 킥오프 3시간 후이고 아직 끝나지 않은 경기가 있음 (빠른 갱신)
full: 6시간마다 한 번 (UTC 0·6·12·18시 첫 실행) — 레이팅·외부 요인·날씨까지
"""
import csv, datetime as dt
from pathlib import Path

ROOT = Path(__file__).parent
now = dt.datetime.now(dt.timezone.utc)
kick = {f"{r['home']}-{r['away']}": dt.datetime.fromisoformat(r['kickoff_utc'].replace('Z', '+00:00'))
        for r in csv.DictReader(open(ROOT/'data/kickoffs.csv', encoding='utf-8'))}
pending = [r for r in csv.DictReader(open(ROOT/'data/matches.csv', encoding='utf-8')) if r['status'] != 'FT']
live = any(-dt.timedelta(minutes=20) <= now - kick[f"{r['home']}-{r['away']}"] <= dt.timedelta(hours=3) for r in pending)
stale = any(now - kick[f"{r['home']}-{r['away']}"] > dt.timedelta(hours=3) for r in pending)   # 끝났는데 아직 FT로 안 바뀐 경기
print('live' if live or stale else 'full' if now.hour % 6 == 0 and now.minute < 10 else 'skip')
