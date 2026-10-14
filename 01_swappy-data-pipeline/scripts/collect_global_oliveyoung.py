"""
올리브영 글로벌(global.oliveyoung.com, 영어) 카테고리 수집기.

국내 사이트(oliveyoung.co.kr) 수집본은 data/raw/oliveyoung_products_v5.csv이고,
이 스크립트는 그와 별개로 영어로 서비스되는 올리브영 글로벌 사이트를 대상으로 한다.
글로벌 사이트는 목록·상세 정보 모두 공개 JSON API로 노출돼 있어 브라우저 자동화 없이
requests만으로 수집할 수 있다 (network 탭에서 확인한 내부 API, 세션/쿠키 불필요):

  - 목록: POST /display/category/product-data/   (페이지당 최대 100건)
  - 상세: POST /product/description-info         (전성분·용량·제조국 등 법정 표기 정보)

사용법:
    python scripts/collect_global_oliveyoung.py --dry-run          # 목록 1페이지만 확인 (스킨케어)
    python scripts/collect_global_oliveyoung.py                    # 스킨케어 전체 수집 (중단 후 재실행하면 이어서)
    python scripts/collect_global_oliveyoung.py --limit 200        # 상위 200건만
    python scripts/collect_global_oliveyoung.py --ctgr-no 1000000011 --name suncare   # 다른 카테고리 (예: Suncare)

카테고리 코드(전역 nav에서 확인):
    Skincare 1000000008 · Makeup 1000000031 · Bath & Body 1000000052 ·
    Hair 1000000070 · Face Masks 1000000003 · Suncare 1000000011 ·
    Men`s Care 1000000119 · Wellness 1000000095 · Supplements 1000000134 · Special Value Sets 1000000151

출력: data/raw/global/global_oliveyoung_{name}.csv
체크포인트: data/raw/global/.global_{name}_checkpoint.json (git 제외) — 이미 수집한 prdtNo를 기록해 재실행 시 건너뛴다.
"""

import argparse
import csv
import html
import json
import os
import random
import sys
import time
from datetime import datetime, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Windows 콘솔(cp949)에서 한글 print가 깨지는 것을 막는다. 리다이렉트 등으로 stdout이
# 없거나 reconfigure를 지원하지 않는 환경(일부 IDE 콘솔)에서는 조용히 넘어간다.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

BASE = "https://global.oliveyoung.com"
LIST_URL = f"{BASE}/display/category/product-data/"
DETAIL_URL = f"{BASE}/product/description-info"
IMG_BASE = "https://cdn-image.oliveyoung.com/"
PRODUCT_URL_TMPL = f"{BASE}/product/detail?prdtNo={{}}"

# 스킨케어 최상위 카테고리 — 하위(모이스처라이저/클렌저/토너 등)를 전부 포함해 반환한다.
# --ctgr-no로 다른 카테고리를 넘기면 이 기본값 대신 그쪽을 쓴다.
SKINCARE_CTGR_NO = "1000000008"

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "raw", "global")

HEADER = [
    "카테고리", "브랜드", "상품명", "정상가(USD)", "판매가(USD)", "평점", "리뷰수",
    "화장품성분", "사용기한", "내용량", "제조국", "제조사", "사용방법", "적합피부타입",
    "품절여부", "이미지URL", "상품URL", "수집일시",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 상세 정보 응답의 codeDtlName(영어 라벨) → CSV 칼럼 매핑.
# 사이트가 라벨 문구를 바꾸면 매핑이 깨질 수 있어 부분일치로 잡는다.
DETAIL_LABEL_MAP = {
    "content volume or weight": "내용량",
    "ideal for": "적합피부타입",
    "expiration date": "사용기한",
    "how to use": "사용방법",
    "cosmetics manufacturers": "제조사",
    "country of manufacture": "제조국",
    "ingredients": "화장품성분",
}


def make_session(ctgr_no: str) -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=5, backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST", "GET"],
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json, text/plain, */*",
        "Referer": f"{BASE}/display/category?ctgrNo={ctgr_no}",
    })
    return s


def fetch_listing_page(session: requests.Session, ctgr_no: str, page_num: int, rows: int = 100) -> dict:
    payload = {
        "accParam": "", "langCode": "en", "previewDate": "", "encKey": "", "encText": "",
        "dlvCntry": "9999", "mrgnCntryCode": "", "attrValNo": "",
        "ctgrNo": ctgr_no, "prdtSortStdrCode": "10",
        "pageNum": page_num, "rowsPerPage": str(rows),
        "attrValNoList": {}, "brandNoList": [], "ctgrNoList": [],
        "eventSlprcDscntRt": [], "reviewScore": [], "scrollY": 0,
    }
    r = session.post(LIST_URL, data=json.dumps(payload), timeout=20)
    r.raise_for_status()
    return r.json()


def fetch_detail(session: requests.Session, prdt_no: str) -> dict:
    r = session.post(DETAIL_URL, data=json.dumps({"prdtNo": prdt_no}), timeout=20)
    r.raise_for_status()
    return r.json()


def clean(text: str) -> str:
    if not text:
        return ""
    return html.unescape(text).strip().replace("\r\n", " ").replace("\n", " ").strip()


def load_checkpoint(checkpoint_path: str) -> set:
    if os.path.exists(checkpoint_path):
        with open(checkpoint_path, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_checkpoint(checkpoint_path: str, done: set) -> None:
    with open(checkpoint_path, "w", encoding="utf-8") as f:
        json.dump(sorted(done), f)


def collect(ctgr_no: str, name: str, limit: int | None, sleep_range: tuple[float, float], dry_run: bool) -> None:
    out_csv = os.path.join(OUT_DIR, f"global_oliveyoung_{name}.csv")
    checkpoint_path = os.path.join(OUT_DIR, f".global_{name}_checkpoint.json")

    os.makedirs(OUT_DIR, exist_ok=True)
    session = make_session(ctgr_no)

    print(f"[1/2] 목록 수집 중 (올리브영 글로벌 · {name})…")
    first = fetch_listing_page(session, ctgr_no, 1)
    total = first["hits"]["found"]
    print(f"      전체 {total}건")

    if dry_run:
        sample = first["hits"]["hit"][:3]
        for h in sample:
            f = h["fields"]
            print(f"  - [{f['brandName']}] {f['prdtName']} (${f.get('saleAmt')}, {f.get('reviewCnt')}건 리뷰)")
        print("dry-run: 목록 확인만 하고 종료합니다.")
        return

    items: dict[str, dict] = {}
    for h in first["hits"]["hit"]:
        f = h["fields"]
        items[f["prdtNo"]] = f
    page = 1
    while len(items) < total and (limit is None or len(items) < limit):
        page += 1
        data = fetch_listing_page(session, ctgr_no, page)
        hits = data["hits"]["hit"]
        if not hits:
            break
        for h in hits:
            f = h["fields"]
            items[f["prdtNo"]] = f
        print(f"      페이지 {page} 수집 — 누적 {len(items)}/{total}")
        time.sleep(random.uniform(*sleep_range))

    prdt_list = list(items.values())
    if limit is not None:
        prdt_list = prdt_list[:limit]

    print(f"[2/2] 상세정보(전성분 등) 수집 중 — 대상 {len(prdt_list)}건")
    done = load_checkpoint(checkpoint_path)
    write_header = not os.path.exists(out_csv)
    f_out = open(out_csv, "a", newline="", encoding="utf-8-sig")
    writer = csv.writer(f_out)
    if write_header:
        writer.writerow(HEADER)

    collected_now = 0
    for i, f in enumerate(prdt_list, 1):
        prdt_no = f["prdtNo"]
        if prdt_no in done:
            continue
        try:
            detail = fetch_detail(session, prdt_no)
        except requests.RequestException as e:
            print(f"  ! {prdt_no} 상세 조회 실패: {e} — 건너뜀 (다음 실행에서 재시도)")
            time.sleep(2)
            continue

        dmap = {"내용량": "", "적합피부타입": "", "사용기한": "", "사용방법": "",
                "제조사": "", "제조국": "", "화장품성분": ""}
        for row in detail.get("description", []):
            label = (row.get("codeDtlName") or "").strip().lower()
            content = clean(row.get("itemCont", ""))
            for key, col in DETAIL_LABEL_MAP.items():
                if key in label:
                    dmap[col] = content
                    break

        # allPathCtgrNameList는 세그먼트가 아니라 "4개씩 한 경로"가 이어 붙은 배열이다
        # (제품이 여러 카테고리에 속하면 4개짜리 경로가 여러 번 반복됨). 첫 경로만 쓴다.
        path_list = f.get("allPathCtgrNameList")
        if isinstance(path_list, list) and path_list:
            cat_path = " > ".join(path_list[:4])
        else:
            cat_path = f.get("ctgrName", "")

        writer.writerow([
            cat_path,
            f.get("brandName", ""),
            f.get("prdtName", ""),
            f.get("nrmlAmt", ""),
            f.get("saleAmt", ""),
            f.get("reviewScore", ""),
            f.get("reviewCnt", ""),
            dmap["화장품성분"],
            dmap["사용기한"],
            dmap["내용량"],
            dmap["제조국"],
            dmap["제조사"],
            dmap["사용방법"],
            dmap["적합피부타입"],
            "Y" if f.get("soldOutYn") == "Y" else "N",
            IMG_BASE + f.get("imagePath", "") if f.get("imagePath") else "",
            PRODUCT_URL_TMPL.format(prdt_no),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ])
        done.add(prdt_no)
        collected_now += 1

        if collected_now % 25 == 0:
            f_out.flush()
            save_checkpoint(checkpoint_path, done)
            print(f"      {i}/{len(prdt_list)} ({collected_now}건 신규) — 체크포인트 저장")

        time.sleep(random.uniform(*sleep_range))

    f_out.close()
    save_checkpoint(checkpoint_path, done)
    print(f"완료 — 이번 실행 신규 {collected_now}건, 누적 체크포인트 {len(done)}건")
    print(f"CSV: {out_csv}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="목록 1페이지만 확인하고 종료")
    ap.add_argument("--limit", type=int, default=None, help="수집할 최대 제품 수 (기본: 전체)")
    ap.add_argument("--min-delay", type=float, default=0.35, help="요청 간 최소 대기(초)")
    ap.add_argument("--max-delay", type=float, default=0.7, help="요청 간 최대 대기(초)")
    ap.add_argument("--ctgr-no", default=SKINCARE_CTGR_NO, help="올리브영 글로벌 카테고리 코드 (기본: 스킨케어)")
    ap.add_argument("--name", default="skincare", help="출력 파일에 쓸 카테고리 이름 (기본: skincare)")
    args = ap.parse_args()

    try:
        collect(args.ctgr_no, args.name, args.limit, (args.min_delay, args.max_delay), args.dry_run)
    except KeyboardInterrupt:
        print("\n중단됨 — 체크포인트까지는 저장돼 있습니다. 다시 실행하면 이어서 수집합니다.")
        sys.exit(130)
