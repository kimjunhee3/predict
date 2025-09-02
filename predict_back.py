# -*- coding: utf-8 -*-
import os
import unicodedata
import requests
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from bs4 import BeautifulSoup

from statiz_reader import (
    fetch_remote_into_cache,
    get_today_predlist,
    find_match_for_team,
    _today_kst_str,
    get_pred_rows_for_date,   # 디버그용
)

app = Flask(__name__, template_folder="templates", static_folder="static")

# React 등 외부에서 /api/* 호출 허용
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "*")
CORS(app, resources={r"/api/*": {"origins": FRONTEND_ORIGIN}})

# 팀/색상
teams = ["한화", "LG", "KT", "두산", "SSG", "키움", "KIA", "NC", "롯데", "삼성"]
team_colors = {
    "한화": "#f37321", "LG": "#c30452", "KT": "#231f20", "두산": "#13294b",
    "SSG": "#d50032", "키움": "#5c0a25", "KIA": "#d61c29", "NC": "#1a419d",
    "롯데": "#c9252c", "삼성": "#0d3383"
}

# 영문 ↔ 한글 팀명 매핑 (iframe에서 영문이 와도 처리)
TEAM_EN_TO_KO = {
    "Samsung": "삼성", "Hanwha": "한화", "Doosan": "두산", "Kiwoom": "키움", "Lotte": "롯데",
    "SSG": "SSG", "NC": "NC", "KIA": "KIA", "LG": "LG", "KT": "KT",
    # 한글도 그대로 통과
    "삼성": "삼성", "한화": "한화", "두산": "두산", "키움": "키움", "롯데": "롯데",
}
def to_korean_team(name: str) -> str:
    if not name:
        return ""
    return TEAM_EN_TO_KO.get(str(name).strip(), str(name).strip())

# ---- 이미지: 로컬 static/player 사용 + NC/SSG 정규화(NFC/NFD) 보정 ----
PLAYER_IMG_FILES = {
    "한화": {"투수": "한화_투수.png", "야수": "한화_야수.png"},
    "LG": {"투수": "엘지_투수.png", "야수": "엘지_야수.png"},
    "KT": {"투수": "KT_투수.png", "야수": "KT_야수.png"},
    "두산": {"투수": "두산_투수.png", "야수": "두산_야수.png"},
    "SSG": {"투수": "SSG_투수.png", "야수": "SSG_야수.png"},
    "키움": {"투수": "키움_투수.png", "야수": "키움_야수.png"},
    "KIA": {"투수": "KIA_투수.png", "야수": "KIA_야수.png"},
    "NC": {"투수": "NC_투수.png", "야수": "NC_야수.png"},
    "롯데": {"투수": "롯데_투수.png", "야수": "롯데_야수.png"},
    "삼성": {"투수": "삼성_투수.png", "야수": "삼성_야수.png"},
}

def _static_player_dir() -> str:
    return os.path.join(app.static_folder, "player")

def _exists_any_variants(filename: str) -> str | None:
    """
    macOS에서 한글 파일이 NFD로 커밋된 경우 대비
    원문/NFC/NFD 모두 체크 → 실제 존재하는 파일명을 반환
    """
    base = _static_player_dir()
    # 1) 그대로
    p0 = os.path.join(base, filename)
    if os.path.exists(p0):
        return filename
    # 2) NFC
    nfc = unicodedata.normalize("NFC", filename)
    p1 = os.path.join(base, nfc)
    if os.path.exists(p1):
        return nfc
    # 3) NFD
    nfd = unicodedata.normalize("NFD", filename)
    p2 = os.path.join(base, nfd)
    if os.path.exists(p2):
        return nfd
    return None

def build_player_img_map() -> dict:
    """
    로컬 /static/player 만 사용.
    파일이 없거나 정규화 문제면 default.png 폴백.
    반환값은 {팀: {"투수": "파일명", "야수": "파일명"}} 형태.
    """
    m = {}
    for t in teams:
        files = PLAYER_IMG_FILES.get(t, {})
        p_pitcher = files.get("투수", "default.png")
        p_batter  = files.get("야수", "default.png")

        p_pitcher = _exists_any_variants(p_pitcher) or "default.png"
        p_batter  = _exists_any_variants(p_batter) or "default.png"

        m[t] = {"투수": p_pitcher, "야수": p_batter}
    return m

# ---- NAVER 투표 (옵션: 로컬 스냅샷 사용) ----
NAVER_VOTE_URL = "https://m.sports.naver.com/predict?tab=today&groupId=kbaseball&categoryId=kbo"
USE_NAVER_LIVE = os.environ.get("USE_NAVER_LIVE", "0") == "1"   # 1이면 라이브 요청
ALLOW_NAVER_FALLBACK = os.environ.get("ALLOW_NAVER_FALLBACK", "1") == "1"

def _extract_naver_block(soup: BeautifulSoup, team_name: str):
    match_boxes = soup.select("div.MatchBox_match_box__IW-0f")
    for box in match_boxes:
        teams_ = box.select("div.MatchBox_name__m2MCa")
        percents = box.select("em.MatchBox_rate__nLGcu span.MatchBox_number__qdpPh")
        if len(teams_) == 2 and len(percents) == 2:
            t1, t2 = teams_[0].get_text(strip=True), teams_[1].get_text(strip=True)
            p1, p2 = percents[0].get_text(strip=True), percents[1].get_text(strip=True)
            if team_name in [t1, t2]:
                try:
                    p1f = float(p1.replace('%','').strip())
                    p2f = float(p2.replace('%','').strip())
                except Exception:
                    continue
                return {
                    "team1": t1, "team2": t2,
                    "percent1": p1f,
                    "percent2": p2f,
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
        "User-Agent": ("Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
                       "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1")
    }
    try:
        r = requests.get(NAVER_VOTE_URL, headers=headers, timeout=12)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        return _extract_naver_block(soup, team_name)
    except Exception:
        return None

# ---- 공통 페이로드 ----
def build_payload_for_team(team: str) -> dict:
    cache_json = fetch_remote_into_cache(force=False)
    rows = get_today_predlist(cache_json)  # ← 오늘(KST) 또는 최신 폴백, 'pred:' 포맷 지원
    statiz_match = find_match_for_team(rows, team)

    if USE_NAVER_LIVE:
        naver_match = parse_naver_vote_live(team)
    else:
        naver_match = parse_naver_vote_from_file(team, "fanvote.html")

    # 네이버가 없으면 statiz 비율로 폴백 허용
    if not naver_match and statiz_match and ALLOW_NAVER_FALLBACK:
        lp = float(statiz_match["left_percent"]) if statiz_match.get("left_percent") is not None else 0.0
        rp = float(statiz_match["right_percent"]) if statiz_match.get("right_percent") is not None else 0.0
        naver_match = {
            "team1": statiz_match.get("left_team") or "",
            "team2": statiz_match.get("right_team") or "",
            "percent1": lp, "percent2": rp,
        }

    # 포맷 정리 (문자열 표시 포함)
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

    return {
        "team": team,
        "statiz": statiz_match,
        "naver": naver_match,
        "team_colors": team_colors,
        "has_data": bool(statiz_match),
        "date_key": _today_kst_str(),
    }

# ---- 라우트 ----
@app.route("/", methods=["GET", "POST"])
def index():
    # ✅ GET 쿼리/POST 폼 모두 허용 + 영문 팀명도 한글로 변환
    raw_team = request.values.get("team") or teams[0]
    selected_team = to_korean_team(raw_team)

    payload = build_payload_for_team(selected_team)
    player_img_map = build_player_img_map()  # 파일명만 반환

    return render_template(
        "predict.html",
        teams=teams,
        selected_team=selected_team,
        statiz=payload["statiz"],
        naver=payload["naver"],
        player_img_map=player_img_map,
        team_colors=team_colors
    )

@app.route("/api/teams")
def api_teams():
    return jsonify({"teams": teams})

@app.route("/api/predict")
def api_predict():
    # 프론트(App.js)에서 팀 바꿔 호출할 때 사용
    raw_team = request.args.get("team", teams[0])
    team = to_korean_team(raw_team)
    if team not in teams:
        return jsonify({"error": "unknown team"}), 400
    payload = build_payload_for_team(team)
    payload["player_img_map"] = build_player_img_map()
    return jsonify(payload)

@app.route("/health")
def health():
    return "ok"

@app.route("/debug/player-images")
def debug_player_images():
    return jsonify(build_player_img_map())

@app.route("/debug/cache")
def debug_cache():
    data = fetch_remote_into_cache(force=False)
    today = _today_kst_str()
    today_rows = get_pred_rows_for_date(data, today)
    # 사용 가능한 날짜 나열 (최신 포맷/구포맷 모두)
    dates = sorted({k.split(":")[1] for k in data.keys() if k.startswith(("pred:", "predlist:", "s_nos:"))})
    return jsonify({
        "available_dates": dates,
        "today": today,
        "today_rows_count": len(today_rows),
        "has_today": bool(today_rows),
        "note": "pred:YYYY-MM-DD[:s_no] 우선, 없으면 predlist:YYYY-MM-DD 폴백",
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=True)
