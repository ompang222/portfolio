"""out/results.json + out/history.csv + 엠블럼·킥오프 -> dashboard.html, index.html (데이터를 페이지에 넣어 단독으로 열리는 HTML)."""
import base64, csv, json
from pathlib import Path

ROOT = Path(__file__).parent
data = json.load(open(ROOT/'out/results.json', encoding='utf-8'))
data['history'] = list(csv.DictReader(open(ROOT/'out/history.csv', encoding='utf-8')))
data['logos'] = {p.stem: 'data:image/png;base64,' + base64.b64encode(p.read_bytes()).decode()
                 for p in sorted((ROOT/'data/logos').glob('*.png'))}
data['kickoff'] = {f"{r['home']}-{r['away']}": r['kickoff_utc']
                   for r in csv.DictReader(open(ROOT/'data/kickoffs.csv', encoding='utf-8'))}
fac = ROOT/'data/factors.json'
data['espn_id'] = json.loads(fac.read_text(encoding='utf-8'))['espn_id'] if fac.exists() else {}
meta = ROOT/'data/team_home_adv_meta.json'
data['home_adv_meta'] = json.loads(meta.read_text(encoding='utf-8')) if meta.exists() else None
payload = json.dumps(data, ensure_ascii=False).replace('</', '<\\/')
html = (ROOT/'dashboard_template.html').read_text(encoding='utf-8').replace('/*__DATA__*/null', payload)

# claude.ai 게시용: 문서 뼈대(doctype·head·body)는 게시할 때 붙습니다
(ROOT/'dashboard.html').write_text(html, encoding='utf-8')

# GitHub Pages용: 뼈대를 직접 붙인 단독 페이지
head = ('<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n')
split = html.index('</style>') + len('</style>')
page = head + html[:split] + '\n</head>\n<body>\n' + html[split:] + '\n</body>\n</html>\n'
(ROOT/'index.html').write_text(page, encoding='utf-8')
print('dashboard.html / index.html', len(html)//1024, 'KB')
