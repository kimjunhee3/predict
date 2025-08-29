import os
import requests
from flask import Flask, render_template, request
from bs4 import BeautifulSoup

from statiz_predict import (
    fetch_predictions,
    generate_s_no_list,
    DEFAULT_TTL_MIN,
    _load_cache,
    _today_kst_str,
)

app = Flask(__name__)

teams = ["한화", "LG", "KT", "두산", "SSG", "키움", "KIA", "NC", "롯데", "삼성"]

team_colors = {
    "한화": "#f37321",
    "LG": "#c30452",
    "KT": "#231f20",
    "두산": "#13294b",
    "SSG": "#d50032",
    "키움": "#5c0a25",
    "KIA": "#d61c29",
    "NC": "#1a419d",
    "롯데": "#c9252c",
    "삼성": "#0d3383"
}

NAVER_VOTE_URL = "https://m.sports.naver.com/predict?tab=today&groupId=kbaseball&categoryId=kbo"
USE_NAVER_LIVE = os.environ.get("USE_NAVER_LIVE", "0") == "1"

def _extract_naver_block(soup: BeautifulSoup, team_name: str):
    match_boxes = soup.select("div.MatchBox_match_box__IW-0f")
    for box in match_boxes:
        teams_ = box.select("div.MatchBox_name__m2MCa")
        percents = box.select("em.MatchBox_rate__nLGcu span.MatchBox_number__qdpPh")
        if len(teams_) == 2 and len(percents) == 2:
            t1, t2 = teams_[0].get_text(strip=True), teams_[1].get_text(strip=True)
            p1, p2 = percents[0].get_text(strip=True), percents[1].get_text(strip=True)
            if team_name in [t1, t2]:
                return {
                    "team1": t1, "team2": t2,
                    "percent1": float(p1.replace('%','').strip()),
                    "percent2": float(p2.replace('%','').strip())
                }
    return None

def parse_naver_vote_from_file(team_name, file_path="fanvote.html"):
    if not os.path.exists(file_path):
        return None
    with open(file_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")
    return _extract_naver_block(soup, team_name)

def parse_naver_vote_live(team_name):
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
                      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"
    }
    try:
        resp = requests.get(NAVER_VOTE_URL, headers=headers, timeout=12)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        return _extract_naver_block(soup, team_name)
    except Exception:
        return None

@app.route("/health")
def health():
    return "ok"

# 디버그: s_no 실시간 추출 결과
@app.route("/debug/snos")
def debug_snos():
    try:
        snos = generate_s_no_list(headless=True, use_cache=False, ttl_minutes=DEFAULT_TTL_MIN, force_refresh=True)
        return {"s_nos_live": snos}, 200
    except Exception as e:
        return {"error": str(e)}, 500

# 디버그: 오늘자 캐시 상태
@app.route("/debug/cache")
def debug_cache():
    cache = _load_cache()
    day_key = _today_kst_str()
    return {
        "keys": list(cache.keys())[:100],
        "predlist_today": cache.get(f"predlist:{day_key}")
    }, 200

@app.route("/", methods=["GET", "POST"])
def index():
    selected_team = request.form.get("team") if request.method == "POST" else teams[0]

    # 첫 부팅 타임아웃 시 안전 폴백
    try:
        s_no_list = generate_s_no_list(headless=True, use_cache=True, ttl_minutes=DEFAULT_TTL_MIN)
    except Exception:
        cache = _load_cache()
        day_key = _today_kst_str()
        item = cache.get(f"predlist:{day_key}")
        if item and item.get("data"):
            s_no_list = [r.get("s_no") for r in item["data"] if r.get("s_no")]
        else:
            return render_template(
                "predict.html",
                teams=teams,
                selected_team=selected_team,
                statiz=None,
                naver=None,
                player_img_map={},
                team_colors=team_colors,
            )

    statiz_data = fetch_predictions(s_no_list, headless=True, use_cache=True, ttl_minutes=DEFAULT_TTL_MIN)
    statiz_match = next(
        (m for m in statiz_data if selected_team in [m.get('left_team'), m.get('right_team')]),
        None
    )

    if USE_NAVER_LIVE:
        naver_match = parse_naver_vote_live(selected_team)
    else:
        naver_match = parse_naver_vote_from_file(selected_team, file_path="fanvote.html")

    player_img_map = {
        "한화": {"투수": "한화_투수.png", "야수": "한화_야수.png"},
        "LG": {"투수": "엘지_투수.png", "야수": "엘지_야수.png"},
        "KT": {"투수": "KT_투수.png", "야수": "KT_야수.png"},
        "두산": {"투수": "두산_투수.png", "야수": "두산_야수.png"},
        "SSG": {"투수": "SSG_투수.png", "야수": "SSG_야수.png"},
        "키움": {"투수": "키움_투수.png", "야수": "키움_야수.png"},
        "KIA": {"투수": "KIA_투수.png", "야수": "KIA_야수.png"},
        "NC": {"투수": "NC_투수.png", "야수": "NC_야수.png"},
        "롯데": {"투수": "롯데_투수.png", "야수": "롯데_야수.png"},
        "삼성": {"투수": "삼성_투수.png", "야수": "삼성_야수.png"}
    }

    # 포맷팅
    if statiz_match and statiz_match.get("left_percent") is not None and statiz_match.get("right_percent") is not None:
        statiz_match["left_percent"] = round(float(statiz_match["left_percent"]), 1)
        statiz_match["right_percent"] = round(float(statiz_match["right_percent"]), 1)
        statiz_match["left_percent_str"] = f"{statiz_match['left_percent']:.1f}%"
        statiz_match["right_percent_str"] = f"{statiz_match['right_percent']:.1f}%"

    if naver_match:
        naver_match["percent1"] = float(naver_match["percent1"])
        naver_match["percent2"] = float(naver_match["percent2"])
        naver_match["percent1_str"] = f"{naver_match['percent1']:.1f}%"
        naver_match["percent2_str"] = f"{naver_match['percent2']:.1f}%"

    return render_template(
        "predict.html",
        teams=teams,
        selected_team=selected_team,
        statiz=statiz_match,
        naver=naver_match,
        player_img_map=player_img_map,
        team_colors=team_colors
    )

if __name__ == '__main__':
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=True)
