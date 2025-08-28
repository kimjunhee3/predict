# predict_back.py
import os, json, logging
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, render_template, request, abort, jsonify
from bs4 import BeautifulSoup

app = Flask(__name__)
log = logging.getLogger("predict")
logging.basicConfig(level=logging.INFO)

# ====== 환경 스위치 ======
# 서버에서는 캐시만 사용(권장)
USE_STATIZ_CACHE_ONLY = os.getenv("STATIZ_CACHE_ONLY", "1") == "1"
# Statiz 블록 자체를 끌 수도 있음
ENABLE_STATIZ = os.getenv("ENABLE_STATIZ", "1") == "1"
STATIZ_CACHE_FILE = os.getenv("STATIZ_CACHE_FILE", "statiz_cache.json")
FANVOTE_FILE = os.getenv("FANVOTE_FILE", "fanvote.html")

# ====== 고정 데이터 ======
teams = ["한화","LG","KT","두산","SSG","키움","KIA","NC","롯데","삼성"]
team_colors = {
    "한화":"#f37321","LG":"#c30452","KT":"#231f20","두산":"#13294b","SSG":"#d50032",
    "키움":"#5c0a25","KIA":"#d61c29","NC":"#1a419d","롯데":"#c9252c","삼성":"#0d3383"
}
player_img_map = {
    "한화":{"투수":"한화_투수.png","야수":"한화_야수.png"},
    "LG":{"투수":"엘지_투수.png","야수":"엘지_야수.png"},
    "KT":{"투수":"KT_투수.png","야수":"KT_야수.png"},
    "두산":{"투수":"두산_투수.png","야수":"두산_야수.png"},
    "SSG":{"투수":"SSG_투수.png","야수":"SSG_야수.png"},
    "키움":{"투수":"키움_투수.png","야수":"키움_야수.png"},
    "KIA":{"투수":"KIA_투수.png","야수":"KIA_야수.png"},
    "NC":{"투수":"NC_투수.png","야수":"NC_야수.png"},
    "롯데":{"투수":"롯데_투수.png","야수":"롯데_야수.png"},
    "삼성":{"투수":"삼성_투수.png","야수":"삼성_야수.png"}
}

# ====== 간단 메모리 캐시 ======
_cache = {
    "naver": {"mtime": None, "data": None},
    "statiz": {"loaded_at": None, "data": None},  # loaded_at만 TTL 체크
}
NAVER_TTL = timedelta(seconds=0)  # 파일 mtime 변화로 갱신
STATIZ_TTL = timedelta(minutes=30)

# ====== NAVER 파서 ======
def _parse_naver_all(file_path: str):
    """fanvote.html에서 모든 경기(두 팀/퍼센트) 리스트 파싱"""
    if not Path(file_path).exists():
        return []

    with open(file_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")

    out = []
    for box in soup.select("div.MatchBox_match_box__IW-0f"):
        names = [t.text.strip() for t in box.select("div.MatchBox_name__m2MCa")]
        percs = [p.text.strip() for p in box.select("em.MatchBox_rate__nLGcu span.MatchBox_number__qdpPh")]
        if len(names) == 2 and len(percs) == 2:
            try:
                p1 = float(percs[0])
                p2 = float(percs[1])
            except ValueError:
                continue
            out.append({
                "team1": names[0], "team2": names[1],
                "percent1": p1, "percent2": p2,
                "percent1_str": f"{p1:.1f}%", "percent2_str": f"{p2:.1f}%"
            })
    return out

def get_naver_map():
    """파일 mtime이 바뀌면 다시 파싱하여 팀별 빠른 조회용 dict 반환"""
    fp = Path(FANVOTE_FILE)
    if not fp.exists():
        return {}

    mtime = fp.stat().st_mtime
    if _cache["naver"]["mtime"] != mtime or _cache["naver"]["data"] is None:
        data = _parse_naver_all(FANVOTE_FILE)
        by_team = {}
        for row in data:
            by_team[row["team1"]] = row
            by_team[row["team2"]] = row
        _cache["naver"]["mtime"] = mtime
        _cache["naver"]["data"] = by_team
        log.info("fanvote cache refreshed: %d rows", len(data))
    return _cache["naver"]["data"] or {}

# ====== STATIZ 캐시 로더 ======
def _load_statiz_cache_from_file(path: str):
    if not Path(path).exists():
        return []

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    # 지원 형태 1) {"predlist:yyyymmdd-HHMM": {"data": [...]}}
    keys = [k for k in data.keys() if isinstance(k, str) and k.startswith("predlist:")]
    rows = []
    if keys:
        latest = sorted(keys)[-1]
        rows = list(data.get(latest, {}).get("data", []))

    # 지원 형태 2) 바로 리스트
    if not rows and isinstance(data, list):
        rows = data

    # 문자열/숫자 혼용 보호
    for r in rows:
        for k in ("left_percent", "right_percent"):
            if k in r and r[k] is not None:
                try:
                    r[k] = float(r[k])
                except Exception:
                    r[k] = None
    return rows

def get_statiz_rows():
    if not ENABLE_STATIZ:
        return []

    now = datetime.utcnow()
    loaded_at = _cache["statiz"]["loaded_at"]
    if loaded_at and now - loaded_at < STATIZ_TTL and _cache["statiz"]["data"] is not None:
        return _cache["statiz"]["data"]

    # 서버에선 파일만 사용
    rows = _load_statiz_cache_from_file(STATIZ_CACHE_FILE)
    _cache["statiz"]["data"] = rows
    _cache["statiz"]["loaded_at"] = now
    log.info("statiz cache loaded: %d rows", len(rows))
    return rows

# ====== routes ======
@app.route("/health")
def health():
    return "ok", 200

@app.route("/debug")
def debug():
    if os.getenv("APP_DEBUG") != "1":
        abort(404)

    info = {}
    fp = Path(FANVOTE_FILE)
    info["fanvote_exists"] = fp.exists()
    if fp.exists():
        st = fp.stat()
        info["fanvote_size"] = st.st_size
        info["fanvote_mtime"] = datetime.fromtimestamp(st.st_mtime).isoformat()

    sp = Path(STATIZ_CACHE_FILE)
    info["statiz_cache_exists"] = sp.exists()
    if sp.exists():
        info["statiz_cache_size"] = sp.stat().st_size
        try:
            with open(sp, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                info["statiz_cache_keys"] = [k for k in data.keys()][:5]
        except Exception as e:
            info["statiz_cache_error"] = str(e)

    # 내부 캐시 상태
    info["inmem"] = {
        "naver": {"has": _cache["naver"]["data"] is not None, "mtime": _cache["naver"]["mtime"]},
        "statiz": {"has": _cache["statiz"]["data"] is not None,
                   "loaded_at": _cache["statiz"]["loaded_at"].isoformat() if _cache["statiz"]["loaded_at"] else None}
    }
    return jsonify(info)

@app.route("/", methods=["GET","POST"])
def index():
    selected_team = request.form.get("team") if request.method == "POST" else teams[0]

    # NAVER
    naver_map = get_naver_map()
    naver_match = naver_map.get(selected_team)

    # STATIZ (캐시 파일만)
    statiz_match = None
    if ENABLE_STATIZ:
        for r in get_statiz_rows():
            if selected_team in (r.get("left_team"), r.get("right_team")):
                # 소수점 1자리 표기 필드 추가
                if r.get("left_percent") is not None:
                    r["left_percent_str"] = f"{float(r['left_percent']):.1f}%"
                if r.get("right_percent") is not None:
                    r["right_percent_str"] = f"{float(r['right_percent']):.1f}%"
                statiz_match = dict(r)
                break

    return render_template(
        "predict.html",
        teams=teams, selected_team=selected_team,
        naver=naver_match, statiz=statiz_match,
        team_colors=team_colors, player_img_map=player_img_map
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","8080")), debug=True)

