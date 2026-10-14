"""팀별 홈 이점 — 자국 리그 최근 시즌 홈/원정 기록으로 추정하고, 시즌 간 재현성만큼만 믿는다.

python home_advantage.py   # football-data.co.uk 원자료 받기 → data/team_home_adv.csv, out/home_adv_check.txt
"""
import io, urllib.request
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).parent
RAW = ROOT/'data/domestic'          # 원자료 (.gitignore, 다시 받을 수 있음)
MAIN = ['E0', 'SP1', 'D1', 'I1', 'F1', 'N1', 'P1', 'T1', 'B1', 'G1']
SEASONS = ['2324', '2425', '2526', '2627']
EXTRA = ['NOR', 'AUT']              # 노르웨이·오스트리아 (연도 표기가 다름)

# football-data 표기 → 우리 코드. 체코·슬로바키아·아제르바이잔·우크라이나 리그는 자료가 없어 리그 평균(0)을 씀
FD = {'Arsenal': 'ARS', 'Man City': 'MCI', 'Man United': 'MUN', 'Liverpool': 'LIV', 'Aston Villa': 'AVL',
      'Barcelona': 'BAR', 'Real Madrid': 'RMA', 'Ath Madrid': 'ATM', 'Betis': 'BET', 'Villarreal': 'VIL',
      'Bayern Munich': 'BAY', 'Dortmund': 'BVB', 'RB Leipzig': 'RBL', 'Stuttgart': 'STU',
      'Inter': 'INT', 'Napoli': 'NAP', 'Roma': 'ROM', 'Como': 'COM', 'Paris SG': 'PSG', 'Lille': 'LIL', 'Lens': 'RCL',
      'PSV Eindhoven': 'PSV', 'Feyenoord': 'FEY', 'Sp Lisbon': 'SCP', 'Porto': 'POR', 'Galatasaray': 'GAL',
      'Fenerbahce': 'FEN', 'Club Brugge': 'BRU', 'AEK': 'AEK', 'Bodo/Glimt': 'BOD', 'Viking': 'VIK', 'LASK': 'LAS'}

def download():
    RAW.mkdir(parents=True, exist_ok=True)
    urls = {f'{L}_{s}': f'https://www.football-data.co.uk/mmz4281/{s}/{L}.csv' for L in MAIN for s in SEASONS}
    urls.update({L: f'https://www.football-data.co.uk/new/{L}.csv' for L in EXTRA})
    for name, u in urls.items():
        p = RAW/f'{name}.csv'
        if not p.exists() or name.endswith(SEASONS[-1]):    # 진행 중인 시즌만 매번 새로 받음
            p.write_bytes(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=60).read())

def load():
    frames = []
    for L in MAIN:
        for i, s in enumerate(SEASONS):
            d = pd.read_csv(RAW/f'{L}_{s}.csv', encoding='latin1', usecols=['HomeTeam', 'AwayTeam', 'FTHG', 'FTAG']).dropna()
            frames.append(d.assign(lg=L, si=i))
    for L in EXTRA:
        d = pd.read_csv(RAW/f'{L}.csv', encoding='latin1').rename(columns={'Home': 'HomeTeam', 'Away': 'AwayTeam', 'HG': 'FTHG', 'AG': 'FTAG'})
        start = d['Season'].astype(str).str[:4].astype(int)      # '2023' 또는 '2023/2024' → 2023
        d = d[start >= 2023].assign(lg=L, si=start - 2023)
        frames.append(d[['HomeTeam', 'AwayTeam', 'FTHG', 'FTAG', 'lg', 'si']].dropna())
    return pd.concat(frames, ignore_index=True)

def team_seasons(m):
    """팀·시즌별 홈 이점(골) = (홈 경기당 득실차 − 원정 경기당 득실차)/2, 그리고 리그 평균과의 차이."""
    h = m.assign(team=m.HomeTeam, gd=m.FTHG - m.FTAG, side='H')
    a = m.assign(team=m.AwayTeam, gd=m.FTAG - m.FTHG, side='A')
    g = pd.concat([h, a]).groupby(['lg', 'si', 'team', 'side']).gd.agg(['mean', 'size']).unstack('side')
    t = pd.DataFrame({'ha': (g[('mean', 'H')] - g[('mean', 'A')]) / 2,
                      'n': g[('size', 'H')] + g[('size', 'A')]}).dropna()
    t['ex'] = t.ha - t.groupby(['lg', 'si']).ha.transform('mean')
    return t.reset_index()

if __name__ == '__main__':
    download()
    m = load()
    t = team_seasons(m)
    goals_per_team = (m.FTHG.mean() + m.FTAG.mean()) / 2

    # 재현성: 같은 팀의 '리그 평균 대비 홈 이점'이 다음 시즌에도 이어지는가 (완주한 시즌끼리만)
    full = t[t.n >= 20]
    w = full.pivot_table(index=['lg', 'team'], columns='si', values='ex')
    pairs = pd.concat([w[[i, i + 1]].dropna().set_axis(['a', 'b'], axis=1) for i in range(len(SEASONS) - 1) if i + 1 in w])
    r = float(np.corrcoef(pairs.a, pairs.b)[0, 1])
    r_pos = max(r, 0.0)

    rows = []
    for name, code in FD.items():
        s = t[t.team == name]
        if s.empty:
            continue
        k = len(s)                                      # 시즌 수 (진행 중 시즌은 경기 수 비중으로)
        wt = s.n / s.n.max()
        ex = float(np.average(s.ex, weights=s.n))
        k_eff = float(wt.sum())
        rel = k_eff * r_pos / (1 + (k_eff - 1) * r_pos) if r_pos > 0 else 0.0   # 스피어먼-브라운: k시즌 평균의 신뢰도
        shrunk = rel * ex
        rows.append(dict(code=code, fd_name=name, seasons=k, games=int(s.n.sum()), raw_ex_goals=round(ex, 3),
                         reliability=round(rel, 3), adj_goals=round(shrunk, 3),
                         adj_log=round(shrunk / goals_per_team, 4)))   # 로그 득점비 단위로 환산
    out = pd.DataFrame(rows).sort_values('adj_log', ascending=False)
    out.to_csv(ROOT/'data/team_home_adv.csv', index=False, encoding='utf-8')
    msg = (f'경기 {len(m):,}개 · 팀-시즌 {len(full):,}개\n'
           f'시즌 간 상관(리그 평균 대비 홈 이점) r = {r:.3f}  (쌍 {len(pairs)}개)\n'
           f'팀당 평균 득점 {goals_per_team:.3f}\n\n' + out.to_string(index=False))
    import json
    (ROOT/'data/team_home_adv_meta.json').write_text(json.dumps(dict(r=round(r, 3), pairs=len(pairs), games=len(m),
        team_seasons=len(full), goals_per_team=round(goals_per_team, 3)), ensure_ascii=False), encoding='utf-8')
    (ROOT/'out').mkdir(exist_ok=True)
    (ROOT/'out/home_adv_check.txt').write_text(msg, encoding='utf-8')
    print(msg)
