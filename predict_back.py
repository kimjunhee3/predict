import os, logging, json
from flask import Flask, render_template, request, abort, jsonify
from bs4 import BeautifulSoup
from pathlib import Path
from datetime import datetime

from statiz_predict import fetch_all_predictions_fast, _load_cache, _today_kst_str

app = Flask(__name__)
log = logging.getLogger("predict")
logging.basicConfig(level=logging.INFO)

teams = ["한화","LG","KT","두산","SSG","키움","KIA","NC","롯데","삼성"]
team_colors = {
    "한화":"#f37321","LG":"#c30452","KT":"#231f20","두산":"#13294b","SSG":"#d50032",
    "키움":"#5c0a25","KIA":"#d61c29","NC":"#1a419d","롯데":"#c9252c","삼성":"#0d3383"
}

def parse_naver_vote(team_name, file_path="fanvote.html"):
    p = Path(file_path)
    if not p.exists():
        return None
    soup = BeautifulSoup(p.read_text(encoding="utf-8"), "html.parser")
    boxes = soup.select("div.MatchBox_match_box__IW-0f")
    for box in boxes:
        teams_ = box.select("div.MatchBox_name__m2MCa")
        percents = box.select("em.MatchBox_rate__nLGcu span.MatchBox_number__qdpPh")
        if len(teams_) == 2 and len(percents) == 2:
            t1, t2 = teams_[0].text.strip(), teams_[1].text.strip()
            p1 = percents[0].text.strip().replace(",","")
            p2 = percents[1].text.strip().replace(",","")
            if team_name in (t1, t2):
                return {"team1": t1, "team2": t2,
                        "percent1": float(p1), "percent2": float(p2)}
    return None

@app.route("/health")
def health():
    return "ok", 200

@app.route("/debug")
def debug():
    info = {}

    fanvote_path = Path("fanvote.html")
    info["fanvote_exists"] = fanvote_path.exists()
    if fanvote_path.exists():
        stat = fanvote_path.stat()
        info["fanvote_size"] = stat.st_size
        info["fanvote_mtime"] = datetime.fromtimestamp(stat.st_mtime).isoformat()

    cache_path = Path("statiz_cache.json")
    info["statiz_cache_exists"] = cache_path.exists()
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            info["statiz_cache_keys"] = list(data.keys())[:10]
            info["today_key"] = _today_kst_str()
        except Exception as e:
            info["statiz_cache_error"] = str(e)

    return jsonify(info)

@app.route("/", methods=["GET","POST"])
def index():
    selected_team = request.form.get("team") if request.method == "POST" else teams[0]

    # 1) 네이버 (정적 HTML)
    naver_match = parse_naver_vote(selected_team)

    # 2) STATIZ (캐시가 없거나 TTL 지난 경우 자동 크롤링 후 캐시 저장)
    statiz_match = None
    try:
        rows = fetch_all_predictions_fast(
            headless=True, use_cache=True, ttl_minutes=int(os.getenv("STATIZ_TTL_MIN","30")),
            force_refresh=False, fill_detail=True
        )
        for r in rows:
            if selected_team in (r.get("left_team"), r.get("right_team")):
                statiz_match = dict(r)
                break
    except Exception as e:
        log.error("statiz fetch failed: %s", e)
        # 캐시만 읽어 fallback 하고 싶으면 여기에서 _load_cache()를 사용해도 된다.

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
