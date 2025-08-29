# -*- coding: utf-8 -*-
import os
import requests
from flask import Flask, render_template, request, jsonify
from bs4 import BeautifulSoup

from statiz_reader import (
    fetch_remote_into_cache,
    get_today_predlist,
    find_match_for_team,
    _today_kst_str,
)

app = Flask(__name__)

# 팀 목록/컬러
teams = ["한화", "LG", "KT", "두산", "SSG", "키움", "KIA", "NC", "롯데", "삼성"]
team_colors = {
    "한화": "#f37321", "LG": "#c30452", "KT": "#231f20", "두산": "#13294b", "SSG": "#d50032",
    "키움": "#5c0a25", "KIA": "#d61c29", "NC": "#1a419d", "롯데": "#c9252c", "삼성": "#0d3383"
}

# NAVER (옵션)
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
                    "percent2": float(p2.replace('%','').strip()),
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
        r = requests.get(NAVER_VOTE_URL, headers=headers, timeout=12)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        return _extract_naver_block(soup, team_name)
    except Exception:
        return None

@app.route("/health")
def health():
    return "ok"

@app.route("/debug/cache")
def debug_cache():
    data = fetch_remote_into_cache(force=False)
    keys = list(data.keys())
    pred_today = data.get(f"predlist:{_today_kst_str()}")
    return jsonify({
        "keys_count": len(keys),
        "has_today_predlist": bool(pred_today),
        "today_key": f"predlist:{_today_kst_str()}",
    })

@app.route("/debug/refresh")
def debug_refresh():
    data = fetch_remote_into_cache(force=True)
    return jsonify({"refreshed": True, "keys_count": len(data.keys())})

@app.route("/", methods=["GET", "POST"])
def index():
    selected_team = request.form.get("team") if request.method == "POST" else teams[0]

    # 1) 원격 JSON → /data 캐시로 로드
    cache_json = fetch_remote_into_cache(force=False)

    # 2) 오늘자(없으면 최신) predlist에서 선택팀 경기 찾기
    rows = get_today_predlist(cache_json)
    statiz_match = find_match_for_team(rows, selected_team)

    # 3) NAVER (라이브 or 스냅샷)
    if USE_NAVER_LIVE:
        naver_match = parse_naver_vote_live(selected_team)
    else:
        naver_match = parse_naver_vote_from_file(selected_team, "fanvote.html")

    # 4) NAVER가 없으면 STATIZ 값으로 대체(템플릿 수정 없이 표시되도록)
    if not naver_match and statiz_match:
        lp = float(statiz_match["left_percent"]) if statiz_match.get("left_percent") is not None else 0.0
        rp = float(statiz_match["right_percent"]) if statiz_match.get("right_percent") is not None else 0.0
        naver_match = {
            "team1": statiz_match.get("left_team") or "",
            "team2": statiz_match.get("right_team") or "",
            "percent1": lp,
            "percent2": rp,
        }

    # 5) 퍼센트 포맷팅
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

    # 이미지 매핑(기존과 동일)
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

    return render_template(
        "predict.html",
        teams=teams,
        selected_team=selected_team,
        statiz=statiz_match,
        naver=naver_match,
        player_img_map=player_img_map,
        team_colors=team_colors
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=True)
