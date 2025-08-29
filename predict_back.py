# -*- coding: utf-8 -*-
import os
import re
import unicodedata
import urllib.parse
import requests
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from bs4 import BeautifulSoup

from statiz_reader import (
    fetch_remote_into_cache,
    get_today_predlist,
    find_match_for_team,
    _today_kst_str,
)

app = Flask(__name__)

# CORS: /api/* 만 허용 (원하면 FRONTEND_ORIGIN에 프론트 도메인 지정)
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "*")
CORS(app, resources={r"/api/*": {"origins": FRONTEND_ORIGIN}})

# 원격 이미지(깃허브 raw/jsDelivr 등) 베이스 URL (폴더 단위, 예: .../static/player)
REMOTE_IMAGE_BASE = os.environ.get("REMOTE_IMAGE_BASE", "").rstrip("/")

# 팀/색상
teams = ["한화", "LG", "KT", "두산", "SSG", "키움", "KIA", "NC", "롯데", "삼성"]
team_colors = {
    "한화": "#f37321", "LG": "#c30452", "KT": "#231f20", "두산": "#13294b",
    "SSG": "#d50032", "키움": "#5c0a25", "KIA": "#d61c29", "NC": "#1a419d",
    "롯데": "#c9252c", "삼성": "#0d3383"
}

# NAVER (옵션)
NAVER_VOTE_URL = "https://m.sports.naver.com/predict?tab=today&groupId=kbaseball&categoryId=kbo"
USE_NAVER_LIVE = os.environ.get("USE_NAVER_LIVE", "0") == "1"
ALLOW_NAVER_FALLBACK = os.environ.get("ALLOW_NAVER_FALLBACK", "1") == "1"  # NAVER 없으면 STATIZ 값으로 대체

# --------------------------- 이미지 파일 자동 매칭 ---------------------------
TEAM_ALIASES = {
    "NC": ["NC", "nc", "엔씨"],
    "SSG": ["SSG", "ssg", "에스에스지"],
    "LG": ["LG", "lg", "엘지"],
    "KT": ["KT", "kt"],
    "KIA": ["KIA", "kia"],
    "두산": ["두산"],
    "키움": ["키움"],
    "한화": ["한화"],
    "롯데": ["롯데"],
    "삼성": ["삼성"],
}

def _static_player_dir() -> str:
    return os.path.join(app.static_folder, "player")

def _list_player_files() -> list[str]:
    d = _static_player_dir()
    if not os.path.isdir(d):
        return []
    return [f for f in os.listdir(d) if os.path.isfile(os.path.join(d, f))]

def _nfc_lower(s: str) -> str:
    # 한글 정규화(NFC) + 소문자
    return unicodedata.normalize("NFC", s).lower()

def _resolve_player_filename(team: str, role: str) -> str | None:
    """
    static/player 안에서 팀/역할(투수|야수)에 맞는 파일명을 느슨하게 탐색
    - 대소문자/정규화/언더바·하이픈·실수 공백 허용
    """
    files = _list_player_files()
    if not files:
        return None

    idx = {_nfc_lower(fn): fn for fn in files}
    aliases = TEAM_ALIASES.get(team, [team, team.lower(), team.upper()])
    seps = ["_", "-", "_ ", " -", " _", " - "]
    exts = [".png", ".PNG", ".jpg", ".jpeg", ".webp"]

    # 1) 정석 조합 우선
    for name in aliases:
        for sep in seps:
            base = f"{name}{sep}{role}"
            for ext in exts:
                want = base + ext
                hit = idx.get(_nfc_lower(want))
                if hit:
                    return hit

    # 2) 느슨한 포함 매칭(팀+역할 키워드)
    want_role = _nfc_lower(role)
    alias_norms = [_nfc_lower(a) for a in aliases]
    for fn in files:
        nfn = _nfc_lower(fn)
        if any(a in nfn for a in alias_norms) and want_role in nfn and any(nfn.endswith(e.lower()) for e in exts):
            return idx.get(nfn, fn)

    return None

# ---- 원격 URL 후보(NFC/NFD 등) → 존재하는 것 고르기 ----
def _remote_exists(url: str) -> bool:
    try:
        r = requests.head(url, timeout=5, allow_redirects=True)
        return 200 <= r.status_code < 300
    except Exception:
        return False

def _to_nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)

def _to_nfd(s: str) -> str:
    return unicodedata.normalize("NFD", s)

def _filename_variants(fn: str) -> list[str]:
    """
    NFC/NFD + 팀 영문 접두어의 대/소문자 + 구분자 변형(_/-/공백 실수)까지 후보 생성
    """
    cand = set([fn, _to_nfc(fn), _to_nfd(fn)])

    m = re.match(r"^([A-Za-z]+)(.*)$", fn)
    if m:
        team, rest = m.group(1), m.group(2)
        for tcase in [team.upper(), team.lower(), team.capitalize()]:
            cand.add(tcase + rest)
            cand.add(_to_nfc(tcase + rest))
            cand.add(_to_nfd(tcase + rest))

    seps = [("_ ", "_"), (" -", "-"), (" - ", "-"), (" _", "_")]
    more = set()
    for c in list(cand):
        for a, b in seps:
            more.add(c.replace(a, b))
    cand |= more

    return list(cand)

def _best_remote_url(filename: str) -> str | None:
    if not REMOTE_IMAGE_BASE:
        return None
    for name in _filename_variants(filename):
        url = f"{REMOTE_IMAGE_BASE}/{urllib.parse.quote(name)}"
        if _remote_exists(url):
            return url
    return None

def build_player_img_map() -> dict:
    """
    1) 파일명 추정(자동 탐색)
    2) REMOTE_IMAGE_BASE가 있으면 NFC/NFD 등 여러 후보를 시도해 존재하는 URL 선택
    3) 실패 시 로컬(static) → 그래도 없으면 default.png
    """
    m = {}
    for t in teams:
        name_pitcher = _resolve_player_filename(t, "투수") or "default.png"
        name_batter  = _resolve_player_filename(t, "야수") or "default.png"

        # 로컬 기본 경로
        local_p = f"/static/player/{name_pitcher}"
        local_b = f"/static/player/{name_batter}"
        if not os.path.exists(os.path.join(app.static_folder, "player", name_pitcher)):
            local_p = "/static/player/default.png"
        if not os.path.exists(os.path.join(app.static_folder, "player", name_batter)):
            local_b = "/static/player/default.png"

        if REMOTE_IMAGE_BASE:
            remote_p = _best_remote_url(name_pitcher)
            remote_b = _best_remote_url(name_batter)
            m[t] = {"투수": (remote_p or local_p), "야수": (remote_b or local_b)}
        else:
            m[t] = {"투수": local_p, "야수": local_b}
    return m

# --------------------------- NAVER 파싱 ---------------------------
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

# --------------------------- 디버그/헬스 ---------------------------
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

@app.route("/debug/player-images")
def debug_player_images():
    return jsonify(build_player_img_map())

# --------------------------- 공통 페이로드 ---------------------------
def build_payload_for_team(team: str) -> dict:
    cache_json = fetch_remote_into_cache(force=False)
    rows = get_today_predlist(cache_json)
    statiz_match = find_match_for_team(rows, team)

    # NAVER (라이브 or 파일)
    if USE_NAVER_LIVE:
        naver_match = parse_naver_vote_live(team)
    else:
        naver_match = parse_naver_vote_from_file(team, "fanvote.html")

    # NAVER 없으면(선택) STATIZ로 대체
    if not naver_match and statiz_match and ALLOW_NAVER_FALLBACK:
        lp = float(statiz_match["left_percent"]) if statiz_match.get("left_percent") is not None else 0.0
        rp = float(statiz_match["right_percent"]) if statiz_match.get("right_percent") is not None else 0.0
        naver_match = {
            "team1": statiz_match.get("left_team") or "",
            "team2": statiz_match.get("right_team") or "",
            "percent1": lp,
            "percent2": rp,
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

    return {
        "team": team,
        "statiz": statiz_match,
        "naver": naver_match,
        "team_colors": team_colors,
        "has_data": bool(statiz_match),
        "date_key": f"predlist:{_today_kst_str()}",
    }

# --------------------------- 페이지 렌더 ---------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    selected_team = request.form.get("team") if request.method == "POST" else teams[0]
    payload = build_payload_for_team(selected_team)
    player_img_map = build_player_img_map()

    return render_template(
        "predict.html",
        teams=teams,
        selected_team=selected_team,
        statiz=payload["statiz"],
        naver=payload["naver"],
        player_img_map=player_img_map,
        team_colors=team_colors
    )

# --------------------------- JSON API ---------------------------
@app.route("/api/teams")
def api_teams():
    return jsonify({"teams": teams})

@app.route("/api/predict")
def api_predict():
    team = request.args.get("team", teams[0])
    if team not in teams:
        return jsonify({"error": "unknown team"}), 400
    payload = build_payload_for_team(team)
    payload["player_img_map"] = build_player_img_map()
    return jsonify(payload)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=True)
