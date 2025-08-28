# predict_back.py
import os, logging, json
from flask import Flask, render_template, request, abort, jsonify
from bs4 import BeautifulSoup
from pathlib import Path
from datetime import datetime

ENABLE_STATIZ = os.getenv("ENABLE_STATIZ", "1") == "1"

# 라이브 스크랩은 옵션 (서버에선 종종 막힘)
if ENABLE_STATIZ:
    try:
        from statiz_predict import fetch_all_predictions_fast
    except Exception as _:
        ENABLE_STATIZ = False  # 임포트 실패시 자동 비활성화

app = Flask(__name__)
log = logging.getLogger("predict")
logging.basicConfig(level=logging.INFO)

teams = ["한화","LG","KT","두산","SSG","키움","KIA","NC","롯데","삼성"]

team_colors = {
    "한화":"#f37321","LG":"#c30452","KT":"#231f20","두산":"#13294b","SSG":"#d50032",
    "키움":"#5c0a25","KIA":"#d61c29","NC":"#1a419d","롯데":"#c9252c","삼성":"#0d3383"
}

# ---------- NAVER (fanvote.html) ----------
def parse_naver_vote(team_name, file_path="fanvote.html"):
    if not os.path.exists(file_path):
        return None
    with open(file_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")
    boxes = soup.select("div.MatchBox_match_box__IW-0f")
    for box in boxes:
        teams_ = box.select("div.MatchBox_name__m2MCa")
        percents = box.select("em.MatchBox_rate__nLGcu span.MatchBox_number__qdpPh")
        if len(teams_) == 2 and len(percents) == 2:
            t1, t2 = teams_[0].text.strip(), teams_[1].text.strip()
            p1, p2 = percents[0].text.strip(), percents[1].text.strip()
            if team_name in (t1, t2):
                return {"team1": t1, "team2": t2,
                        "percent1": float(p1), "percent2": float(p2)}
    return None

# ---------- STATIZ 캐시 ----------
CACHE_PATH = Path("statiz_cache.json")

def read_statiz_cache():
    if not CACHE_PATH.exists():
        return None
    try:
        with CACHE_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        # 예상 구조: {"rows": [...], "fetched_at": "..."}
        return data.get("rows") if isinstance(data, dict) else data
    except Exception as e:
        log.error("read_statiz_cache error: %s", e)
        return None

def write_statiz_cache(rows):
    try:
        payload = {"fetched_at": datetime.utcnow().isoformat()+"Z", "rows": rows}
        with CACHE_PATH.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        log.info("statiz cache saved: %s rows", len(rows))
    except Exception as e:
        log.error("write_statiz_cache error: %s", e)

@app.route("/health")
def health():
    return "ok", 200

@app.route("/debug")
def debug():
    if os.getenv("APP_DEBUG") != "1":
        abort(404)
    info = {}
    fanvote_path = Path("fanvote.html")
    info["fanvote_exists"] = fanvote_path.exists()
    if fanvote_path.exists():
        stat = fanvote_path.stat()
        info["fanvote_size"] = stat.st_size
        info["fanvote_mtime"] = datetime.fromtimestamp(stat.st_mtime).isoformat()
    info["statiz_cache_exists"] = CACHE_PATH.exists()
    if CACHE_PATH.exists():
        try:
            with CACHE_PATH.open(encoding="utf-8") as f:
                data = json.load(f)
            rows = data.get("rows", [])
            info["statiz_cache_count"] = len(rows)
            info["statiz_cache_fetched_at"] = data.get("fetched_at")
        except Exception as e:
            info["statiz_cache_error"] = str(e)
    return jsonify(info)

@app.route("/", methods=["GET","POST"])
def index():
    selected_team = request.form.get("team") if request.method == "POST" else teams[0]

    # NAVER (파일)
    naver_match = parse_naver_vote(selected_team)

    # STATIZ: 1) 캐시 읽기 2) 가능하면 라이브 갱신
    statiz_match = None
    rows = read_statiz_cache() or []
    for r in rows:
        if selected_team in (r.get("left_team"), r.get("right_team")):
            statiz_match = dict(r)
            break

    if ENABLE_STATIZ:
        try:
            live_rows = fetch_all_predictions_fast(
                headless=True, use_cache=True, ttl_minutes=30,
                force_refresh=False, fill_detail=True
            )
            if live_rows:
                write_statiz_cache(live_rows)
                # 선택팀 매치 갱신
                for r in live_rows:
                    if selected_team in (r.get("left_team"), r.get("right_team")):
                        statiz_match = dict(r)
                        break
        except Exception as e:
            log.error("statiz live fetch failed: %s", e)

    # 포맷팅
    if statiz_match and statiz_match.get("left_percent") is not None:
        lp = float(statiz_match["left_percent"]); rp = float(statiz_match["right_percent"])
        statiz_match.update({
            "left_percent": round(lp,1), "right_percent": round(rp,1),
            "left_percent_str": f"{lp:.1f}%", "right_percent_str": f"{rp:.1f}%"
        })

    if naver_match:
        p1, p2 = float(naver_match["percent1"]), float(naver_match["percent2"])
        naver_match.update({
            "percent1": p1, "percent2": p2,
            "percent1_str": f"{p1:.1f}%", "percent2_str": f"{p2:.1f}%"
        })

    return render_template(
        "predict.html",
        teams=teams, selected_team=selected_team,
        statiz=statiz_match, naver=naver_match,
        team_colors=team_colors,
        player_img_map={
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
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","8080")), debug=True)
