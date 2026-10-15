"""경기별 외부 요인 모으기 → data/factors.json

- 경기장(도시·나라)과 중립 경기 여부, 원정팀 이동 거리   (ESPN 경기 정보 + Open-Meteo 지오코딩)
- 최근 상대전적 5경기                                    (ESPN seasonseries)
- 휴식일: 직전 경기로부터 며칠 쉬었는지                    (ESPN 팀 일정, 경기 21일 전부터)
- 킥오프 시각 날씨: 강수·풍속·기온                         (Open-Meteo 예보, 경기 15일 전부터)

python factors.py
"""
import csv, json, math, datetime as dt, urllib.parse
from pathlib import Path
from fetch_data import ESPN, ESPN_NAMES, get

ROOT = Path(__file__).parent
OUT = ROOT/'data/factors.json'
SUMMARY = 'https://site.api.espn.com/apis/site/v2/sports/soccer/uefa.champions/summary?event={}'
TEAM_ALL = 'https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{}/schedule'
TEAM_LEAGUE = 'https://site.api.espn.com/apis/site/v2/sports/soccer/{}/teams/{}/schedule?fixture=true'
GEO = 'https://geocoding-api.open-meteo.com/v1/search?count=5&language=en&name={}'
WX = ('https://api.open-meteo.com/v1/forecast?latitude={}&longitude={}&hourly=precipitation,wind_speed_10m,temperature_2m'
      '&start_date={d}&end_date={d}&timezone=UTC')
LEAGUE = {'ARS': 'eng.1', 'MCI': 'eng.1', 'MUN': 'eng.1', 'LIV': 'eng.1', 'AVL': 'eng.1',
          'BAR': 'esp.1', 'RMA': 'esp.1', 'ATM': 'esp.1', 'BET': 'esp.1', 'VIL': 'esp.1',
          'BAY': 'ger.1', 'BVB': 'ger.1', 'RBL': 'ger.1', 'STU': 'ger.1',
          'INT': 'ita.1', 'NAP': 'ita.1', 'ROM': 'ita.1', 'COM': 'ita.1', 'PSG': 'fra.1', 'LIL': 'fra.1', 'RCL': 'fra.1',
          'PSV': 'ned.1', 'FEY': 'ned.1', 'SCP': 'por.1', 'POR': 'por.1', 'GAL': 'tur.1', 'FEN': 'tur.1',
          'BRU': 'bel.1', 'AEK': 'gre.1', 'BOD': 'nor.1', 'VIK': 'nor.1', 'LAS': 'aut.1',
          'SLA': 'cze.1', 'SLO': 'svk.1', 'SAB': 'aze.1', 'SHA': 'ukr.1'}
COUNTRY = {'eng.1': 'England', 'esp.1': 'Spain', 'ger.1': 'Germany', 'ita.1': 'Italy', 'fra.1': 'France',
           'ned.1': 'Netherlands', 'por.1': 'Portugal', 'tur.1': 'Turkey', 'bel.1': 'Belgium', 'gre.1': 'Greece',
           'nor.1': 'Norway', 'aut.1': 'Austria', 'cze.1': 'Czech Republic', 'svk.1': 'Slovakia',
           'aze.1': 'Azerbaijan', 'ukr.1': 'Ukraine'}
GEO_COUNTRY = {'England': 'GB', 'Spain': 'ES', 'Germany': 'DE', 'Italy': 'IT', 'France': 'FR', 'Netherlands': 'NL',
               'Portugal': 'PT', 'Turkey': 'TR', 'Türkiye': 'TR', 'Belgium': 'BE', 'Greece': 'GR', 'Norway': 'NO',
               'Austria': 'AT', 'Czech Republic': 'CZ', 'Czechia': 'CZ', 'Slovakia': 'SK', 'Azerbaijan': 'AZ',
               'Ukraine': 'UA', 'Poland': 'PL', 'Scotland': 'GB', 'Wales': 'GB', 'Hungary': 'HU'}

def haversine(a, b):
    (la1, lo1), (la2, lo2) = [(math.radians(x), math.radians(y)) for x, y in (a, b)]
    h = math.sin((la2 - la1)/2)**2 + math.cos(la1)*math.cos(la2)*math.sin((lo2 - lo1)/2)**2
    return 6371 * 2 * math.asin(math.sqrt(h))

def main():
    F = json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else {'matches': {}, 'geo': {}, 'espn_id': {}}
    rows = list(csv.DictReader(open(ROOT/'data/matches.csv', encoding='utf-8')))
    kick = {f"{r['home']}-{r['away']}": r['kickoff_utc'] for r in csv.DictReader(open(ROOT/'data/kickoffs.csv', encoding='utf-8'))}
    now = dt.datetime.now(dt.timezone.utc)

    # 1) ESPN 경기 id·팀 id
    for d in sorted({r['date'] for r in rows}):
        if all(f"{r['home']}-{r['away']}" in F['matches'] for r in rows if r['date'] == d):
            continue
        for e in get(ESPN.format(d.replace('-', ''))).get('events', []):
            side = {x['homeAway']: x['team'] for x in e['competitions'][0]['competitors']}
            h, a = ESPN_NAMES[side['home']['displayName']], ESPN_NAMES[side['away']['displayName']]
            F['espn_id'][h], F['espn_id'][a] = side['home']['id'], side['away']['id']
            F['matches'].setdefault(f'{h}-{a}', {})['event'] = e['id']
    id2code = {v: k for k, v in F['espn_id'].items()}

    def geocode(city, country):
        key = f'{city}|{country}'
        if key not in F['geo']:
            res = get(GEO.format(urllib.parse.quote(city))).get('results', [])
            cc = GEO_COUNTRY.get(country)
            pick = next((r for r in res if r.get('country_code') == cc), res[0] if res else None)
            F['geo'][key] = [pick['latitude'], pick['longitude']] if pick else None
        return F['geo'][key]

    # 2) 경기장·상대전적 (한 번 받으면 바뀌지 않음; 끝나지 않은 경기만)
    for r in rows:
        k = f"{r['home']}-{r['away']}"; M = F['matches'][k]
        if r['status'] == 'FT' and 'venue' in M:
            continue
        if 'venue' not in M or 'h2h' not in M:
            s = get(SUMMARY.format(M['event']))
            v = s.get('gameInfo', {}).get('venue', {})
            M['venue'] = dict(name=v.get('fullName'), city=v.get('address', {}).get('city'), country=v.get('address', {}).get('country'))
            h2h = []
            for ser in s.get('seasonseries') or []:
                if ser.get('type') != 'head-to-head':
                    continue
                for ev in ser.get('events', []):
                    if not ev.get('statusType', {}).get('completed'):
                        continue
                    cs = {c['homeAway']: c for c in ev['competitors']}
                    hc, ac = id2code.get(cs['home']['team']['id']), id2code.get(cs['away']['team']['id'])
                    if {hc, ac} != {r['home'], r['away']}:
                        continue
                    h2h.append(dict(date=ev['date'][:10], home=hc, away=ac, hg=int(cs['home']['score']),
                                    ag=int(cs['away']['score']), neutral=bool(ev.get('neutralSite'))))
            M['h2h'] = sorted(h2h, key=lambda x: x['date'], reverse=True)[:5]

    # 3) 팀 연고지 = 그 팀의 리그 페이즈 홈경기 경기장 도시 (중립 개최 팀은 자국 수도 대신 실제 홈 개최지)
    base = {}
    for r in rows:
        v = F['matches'][f"{r['home']}-{r['away']}"].get('venue') or {}
        if v.get('city'):
            base.setdefault(r['home'], (v['city'], v['country']))
    for r in rows:
        k = f"{r['home']}-{r['away']}"; M = F['matches'][k]; v = M.get('venue') or {}
        if not v.get('city') or r['away'] not in base:
            continue
        here, frm = geocode(v['city'], v['country']), geocode(*base[r['away']])
        M['dist_km'] = round(haversine(here, frm)) if here and frm else None
        M['neutral'] = GEO_COUNTRY.get(v['country'], v['country']) != GEO_COUNTRY[COUNTRY[LEAGUE[r['home']]]]
        M['coords'] = here

    # 4) 휴식일 (킥오프 21일 전부터), 5) 날씨 (15일 전부터)
    sched = {}
    def team_dates(code):
        if code not in sched:
            tid = F['espn_id'][code]; ds = set()
            for u in (TEAM_ALL.format(tid), TEAM_LEAGUE.format(LEAGUE[code], tid)):
                try:
                    ds |= {e['date'] for e in get(u).get('events', [])}
                except Exception:
                    pass
            ds |= {kick[f"{x['home']}-{x['away']}"] for x in rows if code in (x['home'], x['away'])}   # UCL 경기
            sched[code] = sorted(ds)
        return sched[code]
    wx_fail = []
    for r in rows:
        if r['status'] == 'FT':
            continue
        k = f"{r['home']}-{r['away']}"; M = F['matches'][k]
        ko = dt.datetime.fromisoformat(kick[k].replace('Z', '+00:00'))
        days = (ko - now).total_seconds() / 86400
        if days <= 21:
            for side in ('home', 'away'):
                prev = [d for d in team_dates(r[side]) if d < kick[k]]
                M[f'rest_{side}'] = round((ko - dt.datetime.fromisoformat(prev[-1].replace('Z', '+00:00'))).total_seconds() / 86400, 1) if prev else None
        if days <= 15 and M.get('coords'):
            lat, lon = M['coords']
            try:
                w = get(WX.format(lat, lon, d=ko.date().isoformat()))['hourly']
            except OSError:                      # 날씨 API가 안 되면 이전 예보를 그대로 두고 계속
                wx_fail.append(k); continue
            i = min(ko.hour, len(w['time']) - 1)
            M['weather'] = dict(precip=w['precipitation'][i], wind=w['wind_speed_10m'][i], temp=w['temperature_2m'][i],
                                fetched=now.strftime('%Y-%m-%d %H:%M'))
    OUT.write_text(json.dumps(F, ensure_ascii=False, indent=1), encoding='utf-8')
    nxt = [r for r in rows if r['status'] != 'FT']
    print('경기 정보', len(F['matches']), '· 상대전적 있는 경기', sum(bool(F['matches'][f"{r['home']}-{r['away']}"].get('h2h')) for r in nxt),
          '· 휴식일', sum('rest_home' in F['matches'][f"{r['home']}-{r['away']}"] for r in nxt),
          '· 날씨', sum('weather' in F['matches'][f"{r['home']}-{r['away']}"] for r in nxt),
          '· 중립', [k for k, M in F['matches'].items() if M.get('neutral')])
    if wx_fail:
        print('날씨 못 받음(이전 값 유지):', len(wx_fail), '경기')

if __name__ == '__main__':
    main()
