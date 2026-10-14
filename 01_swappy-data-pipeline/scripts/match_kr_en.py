"""
올리브영 국내(한글, data/raw/oliveyoung_products_v5.csv)와 올리브영 글로벌(영어, data/raw/global/*.csv)에서
같은 상품을 찾아 [한글 상품, 영어 상품]으로 묶는다.

세 단계로 찾는다. 앞 단계에서 짝이 정해진 한글 상품은 뒷 단계에 넘기지 않는다.

  1) 전성분 — data/seed/ingredient_dict.csv(식약처 성분사전)로 한글·영문 성분명을 같은 성분 코드로
     바꾼 뒤 TF-IDF 코사인 유사도로 비교한다. 유사도가 아주 높은 쌍에서 한글↔영문 브랜드 대응표를
     자동으로 뽑고, 브랜드가 다른 쌍은 버린다. 점수 높은 순으로 1:1 배정.
  2) 전성분(구성 다름) — 1단계에서 짝을 못 얻은 한글 상품이라도, 같은 브랜드의 영어 상품과
     전성분이 사실상 같으면(≥0.9) 그 영어 상품이 이미 다른 한글 상품과 짝이어도 묶는다.
     국내의 용량·증정 구성만 다른 기획 상품이 여기에 해당한다.
  3) 상품명 검색 — 글로벌 사이트 검색 API는 봇 차단이 걸려 있어, 글로벌 카테고리 전체를 받아 둔
     목록(scripts/collect_global_oliveyoung.py) 안에서 이름으로 찾는다. 1단계 고신뢰 쌍에서
     한글↔영어 단어 대응표(크림↔cream, 시카↔cica …)를 학습하고, 같은 브랜드 안에서 상품명 단어가 얼마나 서로 대응되는지로 점수를 낸다.
     전성분이 비어 있는 상품도 여기서 찾는다.

사용법:
    python scripts/match_kr_en.py            # 매칭 후 CSV 저장
    python scripts/match_kr_en.py --eval     # 3단계(상품명 검색)의 정확도를 1단계 정답으로 검증
출력 (data/raw/):
    oliveyoung_kr_en_paired.csv     v5와 같은 칼럼으로, 한글 행 바로 아래 영어 행을 두는 합본
    oliveyoung_kr_en_paired_kr.csv  합본에서 한글 행만 (쌍번호로 영어본과 이어진다)
    oliveyoung_kr_en_paired_en.csv  합본에서 영어 행만
"""

import argparse
import csv
import glob
import html
import math
import os
import random
import re
import sys
from collections import Counter, defaultdict

import numpy as np
from scipy.sparse import csr_matrix
from sklearn.preprocessing import normalize

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(REPO, "data", "raw")
DICT_PATH = os.path.join(REPO, "data", "seed", "ingredient_dict.csv")
KR_PATH = os.path.join(RAW, "oliveyoung_products_v5.csv")
EN_GLOB = os.path.join(RAW, "global", "global_oliveyoung_*.csv")
OUT_PAIRED = os.path.join(RAW, "oliveyoung_kr_en_paired.csv")
OUT_KR = os.path.join(RAW, "oliveyoung_kr_en_paired_kr.csv")
OUT_EN = os.path.join(RAW, "oliveyoung_kr_en_paired_en.csv")

MIN_SCORE = 0.55        # 1단계 성분 코사인 최소치 (브랜드 일치 전제)
BRAND_SEED_SCORE = 0.9  # 브랜드 대응표·단어 대응표를 뽑을 때 쓰는 고신뢰 쌍 기준
SAME_FORMULA = 0.9      # 2단계: 이 이상이면 구성만 다른 같은 제품으로 본다
NAME_MIN = 0.6          # 3단계 상품명 점수 최소치 (--eval로 정한 값)
NAME_INGR_VETO = 0.3   # 3단계: 양쪽 전성분이 모두 있으면 코사인이 최소 이 정도는 돼야 한다
NAME_MARGIN = 0.12      # 3단계: 1등과 2등 후보의 점수 차가 이보다 작으면 애매하다고 보고 버린다

METHOD_INGR = "전성분"
METHOD_SAME = "전성분(구성 다름)"
METHOD_NAME = "상품명 검색"


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


# ── 성분명 정규화 ────────────────────────────────────────────────
def key_of(s):
    s = s.lower()
    s = re.sub(r"[\s\-_·'’\"]", "", s)
    return s


def key_noparen(s):
    return key_of(re.sub(r"\([^()]*\)", "", s))


def build_dict():
    exact, loose = {}, {}
    for row in read_csv(DICT_PATH):
        code = row["code"]
        for col in ("std_ko", "old_ko", "std_en", "old_en"):
            v = row[col].strip()
            if not v:
                continue
            exact.setdefault(key_of(v), code)
            loose.setdefault(key_noparen(v), code)
    return exact, loose


def split_ingredients(text):
    t = text.replace("\n", " ")
    t = re.sub(r"\[[^\]]*\]", ",", t)                       # [본품], [Madecassoside] 같은 구획 제목
    t = re.sub(r"\([^()]*\d[^()]*\)", "", t)                # (50 ppm), (10,000ppm), (1%)
    parts = re.split(r"(?<!\d),|,(?!\d)|;|/(?=\s)|•|·", t)  # 1,2-헥산다이올의 쉼표는 보존
    if len(parts) == 1 and " " in t.strip() and re.search(r"[가-힣]", t):
        parts = t.split()                                     # 공백 구분 한글 전성분
    return [p.strip(" .*") for p in parts if p.strip(" .*")]


def to_codes(text, exact, loose):
    codes = []
    for p in split_ingredients(text):
        c = exact.get(key_of(p)) or loose.get(key_noparen(p))
        codes.append(c if c else "raw:" + key_noparen(p))
    return codes


# ── 용량·이름 숫자 ────────────────────────────────────────────────
VOL = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|g|매|ea|sheets?|pcs)\b", re.I)


def volumes(*texts):
    out = set()
    for t in texts:
        for n, u in VOL.findall(t or ""):
            out.add(float(n))
    return out


def name_numbers(name):
    return {n for n in re.findall(r"\d+", name) if len(n) >= 2}


# ── 상품명 토큰 ──────────────────────────────────────────────────
KR_STOP = {"기획", "증정", "세트", "단품", "택", "택1", "더블", "한정", "한정판", "리필", "대용량", "매", "입", "개",
           "종", "콜라보", "에디션", "특가", "구성", "본품", "추가", "스페셜", "선택", "ml", "g", "ea", "p", "x"}
EN_STOP = {"set", "ea", "pack", "special", "double", "oy", "exclusive", "options", "option", "refill", "ml", "g",
           "p", "x", "the", "and", "with", "of", "for", "edition", "limited", "twin", "duo", "trio", "bundle",
           "pcs", "sheets", "sheet", "a", "in", "only", "value", "kit", "gift", "ver", "new"}
TOKEN = re.compile(r"[가-힣]+|[a-z]+|\d+(?:\.\d+)?")


def name_tokens(name, brand_words, stop):
    s = html.unescape(name).lower()
    toks = []
    for t in TOKEN.findall(s):
        if t in stop or t in brand_words:
            continue
        toks.append(t)
    return toks


def brand_words_of(*brands):
    out = set()
    for b in brands:
        out |= set(TOKEN.findall(html.unescape(b).lower()))
    return out


def segment(tok, vocab):
    """붙여 쓴 한글 복합어(수분진정크림)를 학습된 단어(수분·진정·크림)로 쪼갠다. 앞에서부터 가장 긴 일치."""
    if tok in vocab or not re.match(r"[가-힣]", tok) or len(tok) <= 2:
        return [tok]
    out, i = [], 0
    while i < len(tok):
        for L in range(len(tok) - i, 0, -1):
            piece = tok[i:i + L]
            if piece in vocab or L == 1:
                out.append(piece)
                i += L
                break
    # 한 글자 조각만 잔뜩 나오면 원래 토큰을 그대로 쓴다
    return out if sum(len(p) >= 2 for p in out) >= len(out) / 2 else [tok]


class NameMatcher:
    def __init__(self, train_pairs, kr_toks, en_toks):
        ck, ce, cke = Counter(), Counter(), Counter()
        for i, j in train_pairs:
            ks, es = set(kr_toks[i]), set(en_toks[j])
            ck.update(ks)
            ce.update(es)
            for k in ks:
                for e in es:
                    cke[(k, e)] += 1
        self.k2e, self.e2k = defaultdict(dict), defaultdict(dict)
        for (k, e), c in cke.items():
            if c < 2:
                continue
            dice = 2 * c / (ck[k] + ce[e])
            if dice >= 0.2:
                self.k2e[k][e] = dice
                self.e2k[e][k] = dice
        self.kr_vocab = {k for k, c in ck.items() if c >= 2}
        n = max(len(train_pairs), 1)
        self.k_idf = {k: math.log(1 + n / c) for k, c in ck.items()}
        self.e_idf = {e: math.log(1 + n / c) for e, c in ce.items()}
        self.default_idf = math.log(1 + n)

    def seg(self, toks):
        out = []
        for t in toks:
            out.extend(segment(t, self.kr_vocab))
        return out

    @staticmethod
    def _cover(src, dst, table, idf, default_idf):
        if not src:
            return 0.0
        dst = set(dst)
        num = den = 0.0
        for t in set(src):
            w = idf.get(t, default_idf)
            m = 1.0 if t in dst else max((table.get(t, {}).get(d, 0.0) for d in dst), default=0.0)
            num += w * min(m * 1.5, 1.0)  # dice 0.67 이상이면 온전한 대응으로 친다
            den += w
        return num / den

    def score(self, ktoks, etoks):
        a = self._cover(ktoks, etoks, self.k2e, self.k_idf, self.default_idf)
        b = self._cover(etoks, ktoks, self.e2k, self.e_idf, self.default_idf)
        return 0.0 if a + b == 0 else 2 * a * b / (a + b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", action="store_true", help="상품명 검색 단계의 정확도를 검증만 하고 끝낸다")
    args = ap.parse_args()

    exact, loose = build_dict()

    kr = read_csv(KR_PATH)
    en, seen = [], set()
    en_files = sorted(glob.glob(EN_GLOB))
    for p in en_files:
        for row in read_csv(p):
            if row["상품URL"] in seen:
                continue
            seen.add(row["상품URL"])
            en.append(row)
    print(f"영어 파일 {len(en_files)}개: " + ", ".join(os.path.basename(p) for p in en_files))
    print(f"한글 {len(kr)}건 · 영어 {len(en)}건 (중복 제거)")

    kr_codes = [to_codes(r["화장품성분"], exact, loose) if r["화장품성분"].strip() else [] for r in kr]
    en_codes = [to_codes(r["화장품성분"], exact, loose) if r["화장품성분"].strip() else [] for r in en]

    # ── 1단계: 전성분 ────────────────────────────────────────
    vocab, df = {}, Counter()
    for c in kr_codes + en_codes:
        for x in set(c):
            if not x.startswith("raw:"):
                df[x] += 1
    for x in df:
        vocab[x] = len(vocab)
    N = len(kr_codes) + len(en_codes)

    def mat(lst):
        rows, cols, vals = [], [], []
        for i, c in enumerate(lst):
            for x in set(c):
                if x in vocab:
                    rows.append(i); cols.append(vocab[x]); vals.append(np.log(N / df[x]))
        return normalize(csr_matrix((vals, (rows, cols)), shape=(len(lst), len(vocab))))

    sim = (mat(kr_codes) @ mat(en_codes).T).toarray()

    en_brand = [html.unescape(r["브랜드"]).strip().lower() for r in en]
    tally = defaultdict(Counter)
    best_en = sim.argmax(axis=1)
    for i, j in enumerate(best_en):
        if sim[i, j] >= BRAND_SEED_SCORE:
            tally[kr[i]["브랜드"]][en_brand[j]] += 1
    brand_map = {}
    for kb, cnt in tally.items():
        eb, n = cnt.most_common(1)[0]
        if n / sum(cnt.values()) >= 0.6:
            brand_map[kb] = eb
    # 성분으로 못 잡은 브랜드라도 한글 표기가 곧 영문명인 경우(VT, AHC, rdrd …)는 그대로 잇는다
    en_brand_set = set(en_brand)
    for r in kr:
        kb = r["브랜드"]
        if kb not in brand_map and kb.strip().lower() in en_brand_set:
            brand_map[kb] = kb.strip().lower()
    print(f"브랜드 대응 {len(brand_map)}개")

    en_by_brand = defaultdict(list)
    for j, b in enumerate(en_brand):
        en_by_brand[b].append(j)

    kr_vol = [volumes(r["상품명"], r["내용량"]) for r in kr]
    en_vol = [volumes(r["상품명"], r["내용량"]) for r in en]
    kr_num = [name_numbers(r["상품명"]) for r in kr]
    en_num = [name_numbers(r["상품명"]) for r in en]

    cands = []
    for i in range(len(kr)):
        eb = brand_map.get(kr[i]["브랜드"])
        if not eb or not kr_codes[i]:
            continue
        for j in en_by_brand.get(eb, []):
            cos = float(sim[i, j])
            if cos < MIN_SCORE:
                continue
            s = cos + (0.05 if kr_vol[i] & en_vol[j] else 0) + (0.03 if kr_num[i] & en_num[j] else 0)
            cands.append((s, cos, i, j))
    cands.sort(reverse=True)

    used_k, used_e, pairs = set(), set(), []   # pairs: (cos 또는 이름점수, i, j, 방법)
    for s, cos, i, j in cands:
        if i in used_k or j in used_e:
            continue
        used_k.add(i); used_e.add(j)
        pairs.append((cos, i, j, METHOD_INGR))
    n1 = len(pairs)

    # ── 2단계: 전성분이 같은데 구성만 다른 국내 기획 상품 ─────────
    for i in range(len(kr)):
        if i in used_k or not kr_codes[i]:
            continue
        eb = brand_map.get(kr[i]["브랜드"])
        js = en_by_brand.get(eb, []) if eb else []
        if not js:
            continue
        j = max(js, key=lambda j: (sim[i, j], bool(kr_vol[i] & en_vol[j])))
        if sim[i, j] >= SAME_FORMULA:
            used_k.add(i)
            pairs.append((float(sim[i, j]), i, j, METHOD_SAME))
    n2 = len(pairs) - n1

    # ── 3단계: 상품명 검색 ──────────────────────────────────
    kr_bw = [brand_words_of(r["브랜드"], brand_map.get(r["브랜드"], "")) for r in kr]
    en_bw = [brand_words_of(r["브랜드"]) for r in en]
    kr_raw = [name_tokens(r["상품명"], kr_bw[i], KR_STOP) for i, r in enumerate(kr)]
    en_toks = [name_tokens(r["상품명"], en_bw[j], EN_STOP) for j, r in enumerate(en)]
    seed = [(i, j) for cos, i, j, m in pairs if m == METHOD_INGR and cos >= BRAND_SEED_SCORE]

    def search(matcher, i, pool):
        kt = matcher.seg(kr_raw[i])
        scored = []
        for j in pool:
            # 양쪽 다 전성분이 있는데 처방이 딴판이면 이름이 비슷해도 다른 제품이다
            if kr_codes[i] and en_codes[j] and sim[i, j] < NAME_INGR_VETO:
                continue
            s = matcher.score(kt, en_toks[j])
            if kr_vol[i] and en_vol[j]:
                s *= 1.0 if kr_vol[i] & en_vol[j] else 0.85
            scored.append((s, j))
        scored.sort(reverse=True)
        return scored

    if args.eval:
        random.seed(0)
        brands = sorted({kr[i]["브랜드"] for i, _ in seed})
        random.shuffle(brands)
        test_brands = set(brands[: len(brands) // 5])
        train = [(i, j) for i, j in seed if kr[i]["브랜드"] not in test_brands]
        test = [(i, j) for i, j in seed if kr[i]["브랜드"] in test_brands]
        m = NameMatcher(train, kr_raw, en_toks)
        m = NameMatcher(train, [m.seg(t) for t in kr_raw], en_toks)  # 복합어 분절 후 다시 학습
        rows, absent = [], []
        for i, gold in test:
            sc = search(m, i, en_by_brand[brand_map[kr[i]["브랜드"]]])
            if not sc:
                continue
            (s1, j1), s2 = sc[0], (sc[1][0] if len(sc) > 1 else 0.0)
            ok = j1 == gold or sim[i, j1] >= SAME_FORMULA
            rows.append((s1, s1 - s2, ok))
            # 정답이 목록에 없는 경우(국내 전용 상품)를 흉내 낸다: 정답과 같은 전성분 상품을 모두 뺀다
            pool = [j for j in en_by_brand[brand_map[kr[i]["브랜드"]]] if sim[i, j] < SAME_FORMULA and j != gold]
            sc = search(m, i, pool)
            if sc:
                absent.append((sc[0][0], sc[0][0] - (sc[1][0] if len(sc) > 1 else 0.0)))
        print(f"검증 대상 {len(rows)}건 (학습에 안 쓴 브랜드의 전성분 정답 쌍)")
        for th in (0.3, 0.4, 0.5, 0.6, 0.7):
            for mg in (0.0, 0.05, 0.08, 0.12):
                sel = [ok for s, d, ok in rows if s >= th and d >= mg]
                fp = sum(1 for s, d in absent if s >= th and d >= mg)
                if sel:
                    print(f"  점수≥{th} 차이≥{mg}: 정답 있을 때 채택 {len(sel)/len(rows):.0%}·정확도 {sum(sel)/len(sel):.1%}"
                          f" | 정답 없을 때 오채택 {fp/max(len(absent),1):.0%}")
        return

    matcher = NameMatcher(seed, kr_raw, en_toks)
    matcher = NameMatcher(seed, [matcher.seg(t) for t in kr_raw], en_toks)  # 복합어 분절 후 다시 학습
    name_cands = []
    for i in range(len(kr)):
        if i in used_k:
            continue
        eb = brand_map.get(kr[i]["브랜드"])
        pool = [j for j in en_by_brand.get(eb, [])] if eb else []
        if not pool:
            continue
        sc = search(matcher, i, pool)
        if not sc:
            continue
        (s1, j1), s2 = sc[0], (sc[1][0] if len(sc) > 1 else 0.0)
        if s1 >= NAME_MIN and s1 - s2 >= NAME_MARGIN:
            name_cands.append((s1, i, j1))
    name_cands.sort(reverse=True)
    for s, i, j in name_cands:
        if j in used_e:   # 이미 다른 한글 상품과 짝인 영어 상품은 이름만으로는 다시 쓰지 않는다
            continue
        used_k.add(i); used_e.add(j)
        pairs.append((s, i, j, METHOD_NAME))
    n3 = len(pairs) - n1 - n2

    pairs.sort(key=lambda p: (kr[p[1]]["브랜드"], kr[p[1]]["상품명"]))
    write_paired(pairs, kr, en)

    c = Counter(confidence(s, m) for s, i, j, m in pairs)
    print(f"매칭 {len(pairs)}쌍 — 전성분 {n1} / 전성분(구성 다름) {n2} / 상품명 검색 {n3}")
    print(f"신뢰도 — 높음 {c['높음']} / 보통 {c['보통']} / 확인필요 {c['확인필요']}")
    cat = Counter(kr[i]["카테고리"] for s, i, j, m in pairs)
    tot = Counter(r["카테고리"] for r in kr)
    print("카테고리별 — " + ", ".join(f"{k} {cat[k]}/{n}" for k, n in tot.most_common()))
    for path in (OUT_PAIRED, OUT_KR, OUT_EN):
        print(f"저장: {path}")


def confidence(score, method):
    if method == METHOD_NAME:
        return "보통" if score >= 0.7 else "확인필요"
    return "높음" if score >= 0.9 else ("보통" if score >= 0.75 else "확인필요")


def en_as_v5(e):
    """글로벌(영어) 행을 v5 칼럼 이름에 맞춰 옮긴다. v5의 정리용 칼럼(내용량_정리·처리메모 등)은
    국내 데이터 정제 과정에서 생긴 것이라 영어 행에서는 원문을 그대로 두거나 비운다."""
    name = html.unescape(e["상품명"])
    img = e["이미지URL"]
    prdt_no = e["상품URL"].rsplit("=", 1)[-1]
    ext = os.path.splitext(img.split("?")[0])[1] or ".jpg"
    return {
        "카테고리": e["카테고리"].replace("OliveYoungGlobal > ", ""),
        "브랜드": html.unescape(e["브랜드"]),
        "상품명": name,
        "가격": e["판매가(USD)"],
        "평점": e["평점"],
        "리뷰수": e["리뷰수"],
        "화장품성분": e["화장품성분"],
        "사용기한": e["사용기한"],
        "내용량": e["내용량"],
        "내용량_정리": e["내용량"],
        "제조국": e["제조국"],
        "제조사": e["제조사"],
        "이미지파일명": prdt_no + ext if img else "",
        "이미지URL": img,
        "상품URL": e["상품URL"],
        "수집일시": e["수집일시"],
        "카테고리_원본": e["카테고리"],
        "상품명_원본": name,
        "내용량_원본": e["내용량"],
        "화장품성분_원본": e["화장품성분"],
        "정상가": e["정상가(USD)"],
        "사용방법": e["사용방법"],
        "적합피부타입": e["적합피부타입"],
        "품절여부": e["품절여부"],
    }


def write_paired(pairs, kr, en):
    # v5 칼럼 순서를 그대로 쓰되, 가격 칼럼만 통화가 섞이므로 '(원)'을 떼고 통화 칼럼을 둔다.
    v5_cols = list(kr[0].keys())
    rename = {"가격(원)": "가격", "정상가(원)": "정상가"}
    cols = [rename.get(c, c) for c in v5_cols]
    header = ["쌍번호", "언어", "매칭방법", "신뢰도", "점수", "통화"] + cols + ["사용방법", "적합피부타입", "품절여부"]
    files = [open(p, "w", encoding="utf-8-sig", newline="") for p in (OUT_PAIRED, OUT_KR, OUT_EN)]
    both, only_kr, only_en = (csv.DictWriter(f, fieldnames=header, extrasaction="ignore") for f in files)
    for w in (both, only_kr, only_en):
        w.writeheader()
    for n, (s, i, j, m) in enumerate(pairs, 1):
        meta = {"쌍번호": n, "매칭방법": m, "신뢰도": confidence(s, m), "점수": f"{s:.3f}"}
        k_row = {**meta, "언어": "한글", "통화": "KRW", **{rename.get(c, c): v for c, v in kr[i].items()}}
        e_row = {**meta, "언어": "영어", "통화": "USD", **en_as_v5(en[j])}
        both.writerow(k_row)
        both.writerow(e_row)
        only_kr.writerow(k_row)
        only_en.writerow(e_row)
    for f in files:
        f.close()


if __name__ == "__main__":
    main()
