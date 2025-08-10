# analyze.py — Velog 분석 (한국어 날짜/상대시간 파싱 지원)
import json, re
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo  # Py3.9+

IN_PATH = "out.json"
SUMMARY_OUT = "summary.json"
TOPIC_TREND_OUT = "topic_trend.json"

# 묶음 여기서 설정하면 됩니다
STACK_RULES = {
    "Java/JSP/Servlet": {"kw": {"jsp","servlet","jstl","el","tomcat","mvc","java"}, "langs": {"java","jsp"}},
    "DB/SQL": {"kw": {"jdbc","sql","mysql","mariadb","oracle","postgres","db"}, "langs": {"sql"}},
    "Web/FE": {"kw": {"html","css","javascript","js","ts","react","vue","scss"}, "langs": {"javascript","typescript","tsx","jsx","css","scss"}},
}

KST = ZoneInfo("Asia/Seoul")

def parse_korean_datetime(s: str, now: datetime) -> datetime | None:
    """한국어 날짜/상대시간 문자열을 UTC datetime으로 변환"""
    if not s: 
        return None
    text = s.strip()

    # 상대시간: 분/시간/일 전
    m = re.search(r"(약\s*)?(\d+)\s*분\s*전", text)
    if m:
        mins = int(m.group(2))
        return (now - timedelta(minutes=mins)).astimezone(timezone.utc)
    m = re.search(r"(약\s*)?(\d+)\s*시간\s*전", text)
    if m:
        hours = int(m.group(2))
        return (now - timedelta(hours=hours)).astimezone(timezone.utc)
    m = re.search(r"(약\s*)?(\d+)\s*일\s*전", text)
    if m:
        days = int(m.group(2))
        return (now - timedelta(days=days)).astimezone(timezone.utc)

    # 절대시간: 2025. 8. 9 [오전/오후] 9:00(:ss)?
    m = re.search(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})(?:\s*(오전|오후)?\s*(\d{1,2}):(\d{2})(?::(\d{2}))?)?", text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        ampm, hh, mm, ss = m.group(4), m.group(5), m.group(6), m.group(7)
        h = int(hh) if hh else 0
        m_ = int(mm) if mm else 0
        s_ = int(ss) if ss else 0
        if ampm == "오후" and h < 12: h += 12
        if ampm == "오전" and h == 12: h = 0
        kst_dt = datetime(y, mo, d, h, m_, s_, tzinfo=KST)
        return kst_dt.astimezone(timezone.utc)

    return None

def to_utc(dt_str: str | None):
    if not dt_str:
        return None
    # 1) RFC822 (RSS) 시도
    try:
        dt = parsedate_to_datetime(dt_str)
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    # 2) ISO 시도
    try:
        return datetime.fromisoformat(dt_str.replace("Z","+00:00")).astimezone(timezone.utc)
    except Exception:
        pass
    # 3) 한국어 날짜/상대시간 시도
    try:
        now = datetime.now(KST)
        return parse_korean_datetime(dt_str, now)
    except Exception:
        return None

def classify_post(title: str, text: str, tags: list[str], code_langs: list[str]):
    t = (title or "").lower()
    body = (text or "").lower()
    tagset = set(str(x).lower() for x in (tags or []))
    langset = set(str(x).lower() for x in (code_langs or []))

    scores = Counter()
    for topic, rule in STACK_RULES.items():
        s = 0
        if any(kw in t for kw in rule["kw"]) or any(kw in body for kw in rule["kw"]):
            s += 2
        if tagset & rule["kw"]:
            s += 1
        if langset & rule["langs"]:
            s += 2
        if s > 0:
            scores[topic] += s

    is_study = bool(scores) or any(x in body for x in ["정리","개념","설명","예제","코드","실습","에러","해결"])
    major = scores.most_common(1)[0][0] if scores else None
    topics = [k for k,_ in scores.most_common()]
    return is_study, major, topics

def main():
    with open(IN_PATH, encoding="utf-8") as f:
        doc = json.load(f)

    rows = []
    for p in doc.get("posts", []):
        dt = to_utc(p.get("published_at") or "")
        # published_at을 못 구한 경우, 최신 글 기준 상대값이 있었다면 위에서 보정됨.
        if not dt:
            # 날짜가 완전 없더라도 분석에 포함하고 싶다면, 여기서 임시 날짜 부여 가능
            # (예: 오늘 날짜로). 지금은 품질을 위해 스킵 유지.
            pass

        is_study, major, topics = classify_post(
            p.get("title",""), p.get("text",""), p.get("tags",[]), p.get("code_langs",[])
        )

        if dt:
            rows.append({
                "url": p["url"],
                "date": dt.date(),
                "ym": dt.strftime("%Y-%m"),
                "ts": dt,
                "title": p.get("title",""),
                "is_study": is_study,
                "major": major,
                "topics": topics
            })

    rows.sort(key=lambda x: x["ts"])
    if not rows:
        print("no rows")
        with open(SUMMARY_OUT,"w",encoding="utf-8") as f: json.dump({"note":"no data (check published_at format)"}, f, ensure_ascii=False, indent=2)
        with open(TOPIC_TREND_OUT,"w",encoding="utf-8") as f: json.dump({}, f, ensure_ascii=False, indent=2)
        return

    # 활동 구간/간격
    study = [r for r in rows if r["is_study"]] or rows
    start, end = study[0]["date"], study[-1]["date"]

    gaps = []
    for prev, cur in zip(study, study[1:]):
        gaps.append((cur["ts"] - prev["ts"]).days)
    max_gap = max(gaps) if gaps else 0
    cv = 0.0
    if gaps:
        mean = sum(gaps)/len(gaps)
        if mean > 0:
            var = sum((g-mean)**2 for g in gaps)/len(gaps)
            std = var ** 0.5
            cv = std/mean

    # streak
    day_set = set(r["date"] for r in study)
    longest_streak = 0
    cur = 0
    d = start
    while d <= end:
        if d in day_set:
            cur += 1
            longest_streak = max(longest_streak, cur)
        else:
            cur = 0
        d += timedelta(days=1)

    # 최근 90일
    last_ts = study[-1]["ts"]
    win_start = (last_ts - timedelta(days=89)).date()
    last_90 = [r for r in study if win_start <= r["date"] <= last_ts.date()]
    weeks = set(r["ts"].strftime("%G-%V") for r in last_90)
    last_90_weeks_active = len(weeks)
    last_90_posts = len(last_90)

    # 월별
    per_month = defaultdict(int)
    for r in study:
        per_month[r["ym"]] += 1

    # 주제별 월별
    topic_month = defaultdict(lambda: defaultdict(int))
    for r in study:
        buckets = r["topics"] or ([r["major"]] if r["major"] else [])
        for tpc in buckets:
            topic_month[tpc][r["ym"]] += 1
    topic_trend = {t: dict(m) for t,m in topic_month.items()}

    # 점수
    def clamp(x,a,b): return max(a, min(b, x))
    consistency = 100 - clamp((cv*25) + (max_gap*0.5), 0, 100)
    cadence = clamp(consistency*0.7 + min(last_90_posts*3,30)*0.3, 0, 100)

    summary = {
        "author": doc.get("author",{}),
        "active_start": str(start),
        "active_end": str(end),
        "active_days": (end-start).days + 1,
        "total_posts": len(rows),
        "total_study_posts": int(len(study)),
        "posts_per_month": dict(per_month),
        "longest_streak_days": int(longest_streak),
        "max_gap_days": int(max_gap),
        "interval_cv": round(cv,3),
        "last_90d_posts": int(last_90_posts),
        "last_90d_weeks_active": int(last_90_weeks_active),
        "cadence_score": round(cadence,1),
        "top_topics": Counter([r["major"] for r in study if r["major"]]).most_common(5)
    }

    with open(SUMMARY_OUT,"w",encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    with open(TOPIC_TREND_OUT,"w",encoding="utf-8") as f:
        json.dump(topic_trend, f, ensure_ascii=False, indent=2)

    print("== SUMMARY ==")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\n== TOPIC_TREND ==")
    print(json.dumps(topic_trend, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
