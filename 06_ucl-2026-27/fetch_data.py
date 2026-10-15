"""최신 데이터 받기: ESPN 스코어보드(경기 결과·진행 중 스코어) + Opta 파워 레이팅.

python fetch_data.py   # data/matches.csv, data/ratings.csv 갱신
부상 정보(data/injuries.csv)는 기사를 읽고 사람이(또는 Claude가) 직접 고칩니다.
"""
import csv, json, time, datetime as dt, urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/soccer/uefa.champions/scoreboard?dates={}'
OPTA = 'https://dataviz.theanalyst.com/opta-power-rankings/pr-reference.json'
ESPN_NAMES = {
    'Paris Saint-Germain': 'PSG', 'Bayern Munich': 'BAY', 'Real Madrid': 'RMA', 'Liverpool': 'LIV', 'Internazionale': 'INT',
    'Manchester City': 'MCI', 'Arsenal': 'ARS', 'Barcelona': 'BAR', 'Atletico Madrid': 'ATM', 'Atlético Madrid': 'ATM', 'Borussia Dortmund': 'BVB',
    'AS Roma': 'ROM', 'Sporting CP': 'SCP', 'Aston Villa': 'AVL', 'FC Porto': 'POR', 'Manchester United': 'MUN',
    'Club Brugge': 'BRU', 'Real Betis': 'BET', 'PSV Eindhoven': 'PSV', 'Feyenoord Rotterdam': 'FEY', 'Lille': 'LIL',
    'Bodo/Glimt': 'BOD', 'Napoli': 'NAP', 'RB Leipzig': 'RBL', 'Villarreal': 'VIL', 'Fenerbahce': 'FEN',
    'Shakhtar Donetsk': 'SHA', 'Galatasaray': 'GAL', 'Slavia Prague': 'SLA', 'Slovan Bratislava': 'SLO',
    'VfB Stuttgart': 'STU', 'AEK Athens': 'AEK', 'LASK Linz': 'LAS', 'Como': 'COM', 'Lens': 'RCL', 'Viking FK': 'VIK',
    'Sabah FK': 'SAB', 'Sabah': 'SAB', 'Viking': 'VIK', 'RC Lens': 'RCL', 'Inter Milan': 'INT',
}

def get(url, tries=3):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    for i in range(tries):                       # 일시적인 접속 시간 초과는 잠시 뒤 다시 시도
        try:
            return json.load(urllib.request.urlopen(req, timeout=30))
        except OSError:
            if i == tries - 1:
                raise
            time.sleep(5 * (i + 1))

def update_scores():
    path = ROOT/'data/matches.csv'
    rows = list(csv.DictReader(open(path, encoding='utf-8')))
    today = dt.date.today() + dt.timedelta(days=1)          # 유럽 경기는 한국 시간으로 다음 날 새벽
    dates = sorted({r['date'] for r in rows if r['status'] != 'FT' and r['date'] <= today.isoformat()})
    changed, unknown = [], set()
    for d in dates:
        for e in get(ESPN.format(d.replace('-', ''))).get('events', []):
            c = e['competitions'][0]; st = c['status']['type']
            side = {x['homeAway']: x for x in c['competitors']}
            h, a = (ESPN_NAMES.get(side[k]['team']['displayName']) for k in ('home', 'away'))
            if not h or not a:
                unknown.update(side[k]['team']['displayName'] for k in ('home', 'away')); continue
            for r in rows:
                if r['home'] == h and r['away'] == a and r['status'] != 'FT':
                    if st['state'] == 'post' and st.get('completed'):
                        r.update(status='FT', minute='')
                    elif st['state'] == 'in':
                        clock = c['status'].get('displayClock', "0'").split("'")[0]
                        r.update(status='LIVE', minute=min(90, int(clock or 0)))
                    else:
                        continue
                    r.update(hg=side['home']['score'], ag=side['away']['score'])
                    changed.append(f"{h} {r['hg']}-{r['ag']} {a} ({r['status']})")
    w = csv.DictWriter(open(path, 'w', newline='', encoding='utf-8'), fieldnames=rows[0].keys())
    w.writeheader(); w.writerows(rows)
    if unknown: print('이름 매핑 없음:', unknown)
    return changed

def update_ratings():
    path = ROOT/'data/ratings.csv'
    rows = list(csv.DictReader(open(path, encoding='utf-8')))
    data = get(OPTA)
    moved = []
    for r in rows:
        m = [x for x in data if x.get('contestantName') == r['opta_name']]
        b = max(m, key=lambda x: x['currentRating'])
        new = round(b['currentRating'], 2)
        if abs(new - float(r['opta_rating'])) >= 0.01:
            moved.append(f"{r['code']} {r['opta_rating']}→{new}")
        r['opta_rank'], r['opta_rating'] = b['rank'], new
    w = csv.DictWriter(open(path, 'w', newline='', encoding='utf-8'), fieldnames=rows[0].keys())
    w.writeheader(); w.writerows(rows)
    return moved

if __name__ == '__main__':
    print('경기:', update_scores() or '변경 없음')
    print('레이팅:', update_ratings() or '변경 없음')
