"""한 번만 받으면 되는 것: 팀 엠블럼(ESPN, 96px)과 전 경기 킥오프 시각.

python fetch_static.py   # data/logos/<code>.png, data/kickoffs.csv
"""
import csv, json, urllib.request
from pathlib import Path
from fetch_data import ESPN, ESPN_NAMES, get

ROOT = Path(__file__).parent
LOGO = 'https://a.espncdn.com/combiner/i?img=/i/teamlogos/soccer/500/{}.png&h=96&w=96'

rows = list(csv.DictReader(open(ROOT/'data/matches.csv', encoding='utf-8')))
ids, kick = {}, []
for d in sorted({r['date'] for r in rows}):
    for e in get(ESPN.format(d.replace('-', ''))).get('events', []):
        side = {x['homeAway']: x['team'] for x in e['competitions'][0]['competitors']}
        h, a = ESPN_NAMES[side['home']['displayName']], ESPN_NAMES[side['away']['displayName']]
        ids[h], ids[a] = side['home']['id'], side['away']['id']
        kick.append((h, a, e['date']))

(ROOT/'data/logos').mkdir(exist_ok=True)
for code, tid in sorted(ids.items()):
    req = urllib.request.Request(LOGO.format(tid), headers={'User-Agent': 'Mozilla/5.0'})
    (ROOT/f'data/logos/{code}.png').write_bytes(urllib.request.urlopen(req, timeout=60).read())
with open(ROOT/'data/kickoffs.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f); w.writerow(['home', 'away', 'kickoff_utc']); w.writerows(kick)
print(len(ids), 'logos,', len(kick), 'kickoffs')
