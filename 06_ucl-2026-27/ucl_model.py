"""2026-27 UEFA 챔피언스리그 — 경기별 승률·스코어 예측과 우승 확률 시뮬레이션.

python ucl_model.py            # data/*.csv -> out/results.json, out/history.csv
"""
import csv, json, sys, datetime as dt
from pathlib import Path
import numpy as np
from scipy.stats import poisson
from scipy.optimize import minimize, minimize_scalar

ROOT = Path(__file__).parent
N_SIM = 30_000
LONG_RUN_GOALS = 3.2 # 최근 UCL 경기당 평균 득점 (사전값)
PRIOR_GAMES = 60     # 올 시즌 득점 평균을 사전값 쪽으로 당기는 강도
FORM_SD = 1.5        # 남은 시즌 동안 팀 전력이 변할 수 있는 폭 (Opta 레이팅 점수 단위)
DOUBT_WEIGHT = 0.5   # 출전 불투명 선수는 결장 영향의 절반만 반영
MAX_G = 11

def load():
    teams = list(csv.DictReader(open(ROOT/'data/ratings.csv', encoding='utf-8')))
    matches = list(csv.DictReader(open(ROOT/'data/matches.csv', encoding='utf-8')))
    injuries = list(csv.DictReader(open(ROOT/'data/injuries.csv', encoding='utf-8')))
    return teams, matches, injuries

teams, matches, injuries = load()
CODES = [t['code'] for t in teams]
IDX = {c: i for i, c in enumerate(CODES)}
KO = {t['code']: t['team_ko'] for t in teams}
BASE = np.array([float(t['opta_rating']) for t in teams])

def injury_penalty(team, date):
    """그 날짜에 빠지는 선수들의 영향 합계 (레이팅 점수 단위)."""
    s = 0.0
    for r in injuries:
        if r['team'] == team and date < r['until']:
            s += float(r['impact']) * (DOUBT_WEIGHT if r['status'] == 'doubt' else 1.0)
    return s

def eff(team, date):
    return BASE[IDX[team]] - injury_penalty(team, date)

# ── 1. 레이팅 → 기대 득점 변환 계수 추정 ───────────────────────────────
done = [m for m in matches if m['status'] == 'FT']
goals = [int(m['hg']) + int(m['ag']) for m in done]
avg_goals = (LONG_RUN_GOALS * PRIOR_GAMES + sum(goals)) / (PRIOR_GAMES + len(goals))
MU = np.log(avg_goals / 2)

def _probs(lh, la):
    g = np.arange(MAX_G); M = np.outer(poisson.pmf(g, lh), poisson.pmf(g, la))
    return np.tril(M, -1).sum(), np.triu(M, 1).sum()

# (a) 기본값: Opta가 공개한 경기별 승률에 맞춘 계수 (레이팅 1점 차 → 로그 득점비 BETA, 홈 이점 HOME)
opta = list(csv.DictReader(open(ROOT/'data/opta_predictions.csv', encoding='utf-8')))
def sq_err(p):
    b, h = p; s = 0.0
    for o in opta:
        d = BASE[IDX[o['home']]] - BASE[IDX[o['away']]]
        H, A = _probs(np.exp(MU + h + b*d/2), np.exp(MU - h - b*d/2))
        if o['p_home']: s += (H - float(o['p_home']))**2
        if o['p_away']: s += (A - float(o['p_away']))**2
    return s
fit = minimize(sq_err, [0.1, 0.1], method='Nelder-Mead')
BETA, HOME = map(float, fit.x)
OPTA_RMSE = float(np.sqrt(fit.fun / sum(bool(o['p_home']) + bool(o['p_away']) for o in opta)))

# (b) 교차 확인: 올 시즌 실제 경기 결과만으로 추정한 BETA (표본이 작아 참고용)
def nll(beta):
    s = 0.0
    for m in done:
        d = BASE[IDX[m['home']]] - BASE[IDX[m['away']]]
        s -= poisson.logpmf(int(m['hg']), np.exp(MU + HOME + beta*d/2))
        s -= poisson.logpmf(int(m['ag']), np.exp(MU - HOME - beta*d/2))
    return s
BETA_RESULTS = float(minimize_scalar(nll, bounds=(0.02, 0.3), method='bounded').x)

def lambdas(rh, ra, neutral=False):
    h = 0 if neutral else HOME
    return np.exp(MU + h + BETA*(rh-ra)/2), np.exp(MU - h - BETA*(rh-ra)/2)

def score_grid(lh, la, add_h=0, add_a=0):
    g = np.arange(MAX_G)
    M = np.outer(poisson.pmf(g, lh), poisson.pmf(g, la))
    return M / M.sum(), add_h, add_a

def match_card(m):
    date = m['date']; h, a = m['home'], m['away']
    rh, ra = eff(h, date), eff(a, date)
    lh, la = lambdas(rh, ra)
    add_h = add_a = 0
    if m['status'] == 'LIVE':                      # 진행 중: 남은 시간만큼만 추가 득점
        f = max(0, 90 - int(m['minute'] or 0)) / 90
        lh, la = lh*f, la*f; add_h, add_a = int(m['hg']), int(m['ag'])
    M, _, _ = score_grid(lh, la)
    idx = np.argsort(M, axis=None)[::-1][:3]
    tops = [(int(i//MAX_G)+add_h, int(i % MAX_G)+add_a, float(M.flat[i])) for i in idx]
    gh, ga = np.indices(M.shape); gh = gh + add_h; ga = ga + add_a
    return dict(md=int(m['md']), date=date, home=h, away=a, status=m['status'], minute=m['minute'],
                score=(f"{m['hg']}-{m['ag']}" if m['status'] != 'NS' else None),
                p_home=float(M[gh > ga].sum()), p_draw=float(M[gh == ga].sum()), p_away=float(M[gh < ga].sum()),
                xg_home=float(lh + add_h), xg_away=float(la + add_a),
                top_scores=[dict(s=f'{x}-{y}', p=p) for x, y, p in tops],
                inj_home=injury_penalty(h, date), inj_away=injury_penalty(a, date))

# ── 2. 시즌 시뮬레이션 ─────────────────────────────────────────────────
rng = np.random.default_rng(int(sys.argv[1]) if len(sys.argv) > 1 else 2027)
T = len(CODES)
form = rng.normal(0, FORM_SD, size=(N_SIM, T))     # 시뮬레이션마다 팀 전력에 불확실성 부여
pts = np.zeros((N_SIM, T)); gf = np.zeros((N_SIM, T)); ga_ = np.zeros((N_SIM, T)); wins = np.zeros((N_SIM, T))

def add_result(i, j, x, y):
    pts[:, i] += 3*(x > y) + (x == y); pts[:, j] += 3*(y > x) + (x == y)
    gf[:, i] += x; ga_[:, i] += y; gf[:, j] += y; ga_[:, j] += x
    wins[:, i] += x > y; wins[:, j] += y > x

for m in matches:
    i, j = IDX[m['home']], IDX[m['away']]
    if m['status'] == 'FT':
        x = np.full(N_SIM, int(m['hg'])); y = np.full(N_SIM, int(m['ag']))
    else:
        rh = eff(m['home'], m['date']) + form[:, i]; ra = eff(m['away'], m['date']) + form[:, j]
        lh, la = lambdas(rh, ra)
        if m['status'] == 'LIVE':
            f = max(0, 90 - int(m['minute'] or 0)) / 90
            x = int(m['hg']) + rng.poisson(lh*f); y = int(m['ag']) + rng.poisson(la*f)
        else:
            x = rng.poisson(lh); y = rng.poisson(la)
    add_result(i, j, x, y)

gd = gf - ga_
key = pts*1e6 + (gd+500)*1e3 + gf + wins*1e-3 + rng.random((N_SIM, T))*1e-4   # 승점 > 득실차 > 다득점 > 승수
order = np.argsort(-key, axis=1)                  # order[n, k] = k+1위 팀
rank = np.empty_like(order); rank[np.arange(N_SIM)[:, None], order] = np.arange(T)
R_KO = BASE[None, :] + form                       # 토너먼트는 2~5월이라 부상 대신 전력 변동만 반영
ar = np.arange(N_SIM)

def play(i, j, home_i, neutral=False):
    ri, rj = R_KO[ar, i], R_KO[ar, j]
    if neutral:
        li, lj = lambdas(ri, rj, neutral=True)
    else:
        lh, la = lambdas(np.where(home_i, ri, rj), np.where(home_i, rj, ri))
        li, lj = np.where(home_i, lh, la), np.where(home_i, la, lh)
    return rng.poisson(li), rng.poisson(lj), li, lj

def tie(i, j):
    """2차전 홈 = 리그 순위가 높은 팀 (i). 동률이면 연장(30분) → 승부차기(50:50)."""
    x1, y1, *_ = play(i, j, np.zeros(N_SIM, bool))
    x2, y2, li, lj = play(i, j, np.ones(N_SIM, bool))
    a, b = x1 + x2, y1 + y2
    level = a == b
    ea, eb = rng.poisson(li/3), rng.poisson(lj/3)
    a = a + level*ea; b = b + level*eb
    pens = rng.random(N_SIM) < 0.5
    i_wins = (a > b) | ((a == b) & pens)
    return np.where(i_wins, i, j)

def better(i, j):
    return np.where(rank[ar, i] < rank[ar, j], i, j), np.where(rank[ar, i] < rank[ar, j], j, i)

pos = lambda k: order[:, k-1]                      # k위 팀
flip = lambda: rng.random(N_SIM) < 0.5
reach = {s: np.zeros((N_SIM, T), bool) for s in ['R16', 'QF', 'SF', 'F', 'W']}
LEVELS = [((1, 2), (15, 16), (17, 18)), ((3, 4), (13, 14), (19, 20)),
          ((5, 6), (11, 12), (21, 22)), ((7, 8), (9, 10), (23, 24))]
r16w = {}                                          # (level, half) -> R16 승자
for L, (top, up, low) in enumerate(LEVELS):
    f1, f2, f3 = flip(), flip(), flip()
    u1, u2 = np.where(f1, pos(up[0]), pos(up[1])), np.where(f1, pos(up[1]), pos(up[0]))
    l1, l2 = np.where(f2, pos(low[0]), pos(low[1])), np.where(f2, pos(low[1]), pos(low[0]))
    po1, po2 = tie(u1, l1), tie(u2, l2)            # 녹아웃 플레이오프
    t1, t2 = np.where(f3, pos(top[0]), pos(top[1])), np.where(f3, pos(top[1]), pos(top[0]))
    for half, (t, p) in enumerate([(t1, po1), (t2, po2)]):
        reach['R16'][ar, t] = True; reach['R16'][ar, p] = True
        r16w[(L, half)] = tie(t, p)
finalists = []
for half in (0, 1):
    qf = []
    for la_, lb in [(0, 3), (1, 2)]:               # 8강: 1·2위 쪽 vs 7·8위 쪽, 3·4위 쪽 vs 5·6위 쪽
        a, b = r16w[(la_, half)], r16w[(lb, half)]
        reach['QF'][ar, a] = True; reach['QF'][ar, b] = True
        qf.append(tie(*better(a, b)))
    for w in qf: reach['SF'][ar, w] = True
    finalists.append(tie(*better(*qf)))
fa, fb = finalists
reach['F'][ar, fa] = True; reach['F'][ar, fb] = True
x, y, li, lj = play(fa, fb, None, neutral=True)
lvl = x == y
x = x + lvl*rng.poisson(li/3); y = y + lvl*rng.poisson(lj/3)
champ = np.where((x > y) | ((x == y) & (rng.random(N_SIM) < 0.5)), fa, fb)
reach['W'][ar, champ] = True

# ── 3. 저장 ───────────────────────────────────────────────────────────
team_rows = []
for c in CODES:
    i = IDX[c]; r = rank[:, i]
    team_rows.append(dict(
        code=c, team=KO[c], rating=float(BASE[i]), injury_now=injury_penalty(c, '2026-10-20'),
        played=int(sum(1 for m in done if c in (m['home'], m['away']))),
        pts_now=int(sum(3*((m['home'] == c)*(int(m['hg']) > int(m['ag'])) + (m['away'] == c)*(int(m['ag']) > int(m['hg'])))
                        + (int(m['hg']) == int(m['ag'])) for m in done if c in (m['home'], m['away']))),
        exp_pts=float(pts[:, i].mean()),
        top8=float((r < 8).mean()), playoff=float(((r >= 8) & (r < 24)).mean()), out=float((r >= 24).mean()),
        **{k: float(v[:, i].mean()) for k, v in reach.items()}))
team_rows.sort(key=lambda t: -t['W'])
cards = [match_card(m) for m in matches if m['status'] != 'FT']
results = [dict(md=int(m['md']), date=m['date'], home=m['home'], away=m['away'], score=f"{m['hg']}-{m['ag']}")
           for m in done]
now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime('%Y-%m-%d %H:%M KST')
out = dict(updated=now, n_sim=N_SIM, beta=BETA, home=HOME, beta_results=BETA_RESULTS, opta_rmse=OPTA_RMSE, avg_goals=avg_goals, n_done=len(done),
           names=KO, teams=team_rows, cards=cards, results=results,
           injuries=[r for r in injuries])
(ROOT/'out').mkdir(exist_ok=True)
json.dump(out, open(ROOT/'out/results.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
hist = ROOT/'out/history.csv'
new = not hist.exists()
with open(hist, 'a', newline='', encoding='utf-8') as fh:
    w = csv.writer(fh)
    if new: w.writerow(['updated', 'n_done'] + CODES)
    w.writerow([now, len(done)] + [round(float(reach['W'][:, IDX[c]].mean()), 4) for c in CODES])

print(f'beta={BETA:.4f} (경기결과만: {BETA_RESULTS:.4f})  home={HOME:.4f}  Opta 대비 RMSE={OPTA_RMSE:.3f}  avg_goals={avg_goals:.2f}  played={len(done)}')
print(f"{'팀':<12}{'현재':>4}{'기대승점':>8}{'1~8위':>8}{'16강':>7}{'8강':>7}{'4강':>7}{'결승':>7}{'우승':>7}")
for t in team_rows[:16]:
    print(f"{t['team']:<12}{t['pts_now']:>4}{t['exp_pts']:>8.1f}{t['top8']:>8.0%}{t['R16']:>7.0%}{t['QF']:>7.0%}{t['SF']:>7.0%}{t['F']:>7.0%}{t['W']:>7.1%}")
