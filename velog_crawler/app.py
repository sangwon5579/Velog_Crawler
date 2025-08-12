# API 제공
from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import re

# 목록: render_list_with_playwright(handle, max_scrolls, pause_sec, timeout_ms) -> List[str]
# 상세: render_post_with_playwright(url) -> (title, text, code_langs, tags, published)
from crawl_velog import render_list_with_playwright, render_post_with_playwright

app = FastAPI(title="Velog Crawling API")

def normalize_created_at(src: Optional[str]) -> Optional[str]:
    if not src:
        return None
    s = src.strip()
    # 절대 한국어 날짜: 2025. 8. 9 ...
    m = re.search(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y:04d}-{mo:02d}-{d:02d}"
    # 상대시간은 오늘 기준으로 단순 보정(날짜 정보만 필요)
    today = datetime.now().date()
    m = re.search(r"(\d+)\s*일\s*전", s)
    if m:
        d = int(m.group(1))
        day = today.fromordinal(today.toordinal() - d)
        return day.strftime("%Y-%m-%d")
    # 시간/분 전은 오늘 날짜
    if "시간 전" in s or "분 전" in s:
        return today.strftime("%Y-%m-%d")
    # RSS/ISO 케이스
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.date().strftime("%Y-%m-%d")
    except Exception:
        pass
    return None

class PostItem(BaseModel):
    title: str
    url: str
    date: Optional[str] = None
    tags: List[str] = []

class PostDetailReq(BaseModel):
    url: str

class PostDetailRes(BaseModel):
    status: str
    title: str
    createdAt: Optional[str] = None
    content: str  # HTML or Markdown

# 엔드포인트 구현

# 목록: GET /api/v1/velog/posts
# - query: username (필수), page (기본 1), limit (기본 10)
@app.get("/api/v1/velog/posts")
def get_posts(
    username: str = Query(..., description="Velog 사용자명"),   # required
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    # 명세: username 없으면 400 (Missing username)  【명세 근거】.
    # 실제 FastAPI가 위의 required(...)로 422를 내지만, 여기선 400으로 맞춰줌.
    if not username:
        raise HTTPException(status_code=400, detail="Missing username")  # :contentReference[oaicite:8]{index=8}

    try:
        # 전체 링크 수집(Playwright) 후 페이지네이션
        links = render_list_with_playwright(handle=username, max_scrolls=220, pause_sec=1.0)
        if not links:
            # 사용자 없음으로 볼 수 있는 상황 → 404
            raise HTTPException(status_code=404, detail="User not found")  # :contentReference[oaicite:9]{index=9}

        # 페이지네이션 계산
        start = (page - 1) * limit
        stop = start + limit
        page_links = links[start:stop]

        items: List[PostItem] = []
        for url in page_links:
            # 제목/날짜/태그만 가볍게 (상세 전체 렌더는 비용 큼)
            title, _, _, tags, published = render_post_with_playwright(url)
            items.append(PostItem(
                title=title or "",
                url=url,
                date=normalize_created_at(published),  # YYYY-MM-DD
                tags=tags or []
            ))

        return {"status": "success", "data": [i.dict() for i in items]}  # :contentReference[oaicite:10]{index=10}

    except HTTPException:
        raise
    except Exception:
        # 구조 변경 등 크롤 실패 → 500
        raise HTTPException(status_code=500, detail="CRAWLING_FAILED")  # :contentReference[oaicite:11]{index=11}


# 상세: POST /api/v1/velog/post-detail
@app.post("/api/v1/velog/post-detail", response_model=PostDetailRes)
def post_detail(req: PostDetailReq):
    if not req.url:
        raise HTTPException(status_code=400, detail="Missing URL")  # :contentReference[oaicite:12]{index=12}
    try:
        title, text, _, _, published = render_post_with_playwright(req.url)

        # 본문을 HTML로 요구하므로, article의 inner_text 대신 inner_html을 원하면
        # crawl_velog.render_post_with_playwright()를 약간 수정(HTML도 반환)해도 됨.
        # 우선은 text를 그대로 content에 넣고, 필요시 HTML 확장.
        created = normalize_created_at(published)

        if not (title or text):
            # 존재하지 않는 글 처리
            raise HTTPException(status_code=404, detail="Post not found")  # :contentReference[oaicite:13]{index=13}

        return PostDetailRes(
            status="success",  # :contentReference[oaicite:14]{index=14}
            title=title or "",
            createdAt=created,  # YYYY-MM-DD  :contentReference[oaicite:15]{index=15}
            content=text or "",
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="CRAWLING_FAILED")  # :contentReference[oaicite:16]{index=16}
