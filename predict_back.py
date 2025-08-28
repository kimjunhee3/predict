# predict_back.py
import os, re, json, time
from typing import Dict, Any, List, Optional
from flask import Flask, render_template, request
from bs4 import BeautifulSoup

from statiz_predict import fetch_all_predictions_fast  # 목록+상세 하이브리드 (캐시는 내부에서 처리)

app = Flask(__name__)

# ================== 설정 ==================
FANVOTE_HTML_PATH = os.getenv("FANVOTE_HTML_PATH", "fanvote.html")
FANVOTE_CACHE_PATH = os.getenv("FANVOTE_CACHE_PATH", "fanvote_cache.json")
FANVOTE_TTL_MIN   = int(os.getenv("FANVOTE_TTL_MIN", "120"))  # fanvote.html 파싱 캐시 TTL

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

# ================== 유틸: 파일 캐시 ==================
def _load_cache(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_cache(path: str, obj: Dict[str, Any]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def _is_fresh(ts_iso: Optional[str], ttl_min: int) -> bool:
    if not ts_iso: return False
    try:
        ts = time.mktime(time.strptime(ts_iso, "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return False
    return (time.time() - ts) < ttl_min * 60

# ================== 팬투표 파싱 + 캐시 ==================
def _parse_fanvote_all(file_path: str) -> List[Dict[str, Any]]:
    """fanvote.html에서 모든 경기의 (팀1,팀2,퍼센트1,퍼센트2) 리스트를 뽑아온다."""
    with open(file_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")

    # 클래스 접두/정규로 넉넉하게 매칭
    match_boxes = soup.select("div[class^='MatchBox_match_box']")
    if not match_boxes:
        match_boxes = soup.find_all("div", class_=re.compile(r"^MatchBox_match_box"))

    rows: List[Dict[str, Any]] = []
    for box in match_boxes:
        teams_ = box.find_all("div", class_=re.compile(r"^MatchBox_name"))
        # em.MatchBox_rate__... > span.MatchBox_number__...
        percents = box.select("em[class^='MatchBox_rate'] span[class^='MatchBox_number']")
        if len(teams_) == 2 and len(percents) == 2:
            t1 = teams_[0].get_text(strip=True)
            t2 = teams_[1].get_text(strip=True)
            p1 = percents[0].get_text(strip=True).replace("%", "").strip()
            p2 = percents[1].get_text(strip=True).replace("%", "").strip()
            try:
                rows.append({
                    "team1": t1,
                    "team2": t2,
                    "percent1": float(p1),
                    "percent2": float(p2),
                })
            except Exception:
                # 퍼센트가 비정상 문자열인 경우 건너뜀
                pass
    return rows

def _ensure_fanvote_cache() -> Dict[str, Any]:
    """
    fanvote_cache.json 구조:
    {
      "ts": "YYYY-MM-DDTHH:MM:SS",
      "src_mtime": 1724900000.123,        # fanvote.html의 mtime
      "data": [ {team1, team2, percent1, percent2}, ... ]
    }
    - TTL 경과 or fanvote.html mtime 변경 시 재파싱.
    """
    cache = _load_cache(FANVOTE_CACHE_PATH)
    src_mtime = os.path.getmtime(FANVOTE_HTML_PATH) if os.path.exists(FANVOTE_HTML_PATH) else None
    need = True

    if cache and _is_fresh(cache.get("ts"), FANVOTE_TTL_MIN):
        # 소스 파일이 바뀌지 않았으면 재사용
        if (src_mtime is None and cache.get("src_mtime") is None) or (src_mtime == cache.get("src_mtime")):
            need = False

    if need:
        if not os.path.exists(FANVOTE_HTML_PATH):
            # 소스가 없으면 빈 데이터로 초기화(서비스는 동작, 안내 문구 노출)
            cache = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                     "src_mtime": None, "data": []}
            _save_cache(FANVOTE_CACHE_PATH, cache)
            return cache

        data = _parse_fanvote_all(FANVOTE_HTML_PATH)
        cache = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "src_mtime": src_mtime,
            "data": data,
        }
        _save_cache(FANVOTE_CACHE_PATH, cache)

    return cache

def get_naver_match_for_team(team_name: str) -> Optional[Dict[str, Any]]:
    cache = _ensure_fanvote_cache()
    for row in cache.get("data", []):
        if team_name in (row["team1"], row["team2"]):
            # 가독용 포맷팅 추가
            r = dict(row)
            r["percent1_str"] = f"{r['percent1']:.1f}%"
            r["percent2_str"] = f"{r['percent2']:.1f}%"
            return r
    return None

# ================== Flask 뷰 ==================
@app.route("/", methods=["GET", "POST"])
def index():
    selected_team = request.form.get("team") if request.method == "POST" else teams[0]

    # 1) Statiz 승부예측(목록에서 최대한 → 누락만 상세)
    statiz_rows = fetch_all_predictions_fast(
        headless=True, use_cache=True, ttl_minutes=30, force_refresh=False, fill_detail=True
    )
    statiz_match = next((m for m in statiz_rows
                         if selected_team in [m.get("left_team"), m.get("right_team")]), None)

    # 2) Naver 팬투표(로컬 fanvote.html 파싱 + 캐시)
    naver_match = get_naver_match_for_team(selected_team)

    # 후처리(색상/문자열)
    if statiz_match:
        try:
            lp = float(statiz_match.get("left_percent") or 0.0)
            rp = float(statiz_match.get("right_percent") or 0.0)
        except Exception:
            lp = rp = 0.0
        statiz_match["left_percent"]  = round(lp, 1)
        statiz_match["right_percent"] = round(rp, 1)
        statiz_match["left_percent_str"]  = f"{statiz_match['left_percent']:.1f}%"
        statiz_match["right_percent_str"] = f"{statiz_match['right_percent']:.1f}%"

    return render_template(
        "predict.html",
        teams=teams,
        selected_team=selected_team,
        statiz=statiz_match,
        naver=naver_match,
        team_colors=team_colors,
    )

if __name__ == "__main__":
    # 로컬 테스트용
    app.run(host="0.0.0.0", port=5000, debug=True)
