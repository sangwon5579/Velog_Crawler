# 벨로그 크롤링
import json, time, re, hashlib
from urllib.parse import urljoin
from typing import List, Set, Tuple, Optional

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

UA = "SpecGuardBot/1.0 (+https://example.com)"

# 리스트(프로필) 스크롤 수집 
def render_list_with_playwright(
    handle: str,
    max_scrolls: int = 200,
    pause_sec: float = 1.0,
    timeout_ms: int = 25000,
) -> List[str]:

# 프로필 페이지를 열고 아래로 여러 번 스크롤하면서 해당 유저의 모든 글 링크를 수집.

    base = f"https://velog.io/@{handle}"
    hrefs: Set[str] = set()

    with sync_playwright() as p:
        # 디버깅 시 headless=False, slow_mo=200 으로 바꿔 화면 보면서 확인 가능
        browser = p.chromium.launch(headless=True)
        
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900})

        # 이미지/폰트 차단
        try:
            ctx.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in {"image", "font"}
                else route.continue_(),
            )
        except Exception:
            pass

        page = ctx.new_page()
        page.set_default_timeout(timeout_ms)
        page.set_default_navigation_timeout(timeout_ms)

        page.goto(base, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=6000)
        except PWTimeout:
            pass

        def collect_links() -> Set[str]:
            anchors = page.locator("a").evaluate_all(
                "els => els.map(e => e.getAttribute('href') || '')"
            )
            out = set()
            for h in anchors:
                if not h:
                    continue
                if f"/@{handle}/" in h:
                    # 시리즈/팔로워/태그 등 잡링크 제외
                    if any(x in h for x in ["/series/", "/tag/", "/followers", "/following"]):
                        continue
                    out.add(urljoin("https://velog.io", h))
            return out

        last_count = -1
        stagnant = 0
        for _ in range(max_scrolls):
            cur = collect_links()
            hrefs |= cur

            if len(hrefs) == last_count:
                stagnant += 1
            else:
                stagnant = 0
            last_count = len(hrefs)
            if stagnant >= 3:  # 3번 연속 증가 없음 -> 종료
                break

            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(pause_sec)
            try:
                page.wait_for_load_state("networkidle", timeout=3000)
            except PWTimeout:
                pass

        browser.close()

    hrefs = {h for h in hrefs if f"/@{handle}/" in h}
    return sorted(hrefs)

# 글 상세 렌더링 & 파싱
def render_post_with_playwright(
    url: str,
    timeout_ms: int = 20000,
) -> Tuple[str, str, List[str], List[str], Optional[str]]:
   
    # 글 페이지를 렌더링해서 제목/본문/태그/코드 언어/게시 시각(가능하면) 추출.
    # - visible 대기 없이 짧게 시도 -> 폴백 셀렉터 -> 1회 스크롤 재시도
    # - 전체 per-post 워치독 느낌의 제한으로 무한대기 방지
   
    start = time.perf_counter()
    HARD_LIMIT = max(8, timeout_ms / 1000 + 4)  # 포스트당 최대 N초

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900})

        # 이미지/폰트 차단
        try:
            ctx.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in {"image", "font"}
                else route.continue_(),
            )
        except Exception:
            pass

        page = ctx.new_page()
        page.set_default_timeout(timeout_ms)
        page.set_default_navigation_timeout(timeout_ms)

        page.goto(url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except PWTimeout:
            pass

        # 제목
        title = ""
        try:
            title = page.locator("h1").first.inner_text().strip()
        except Exception:
            pass

        # 태그
        tags: List[str] = []
        try:
            tags = [t.strip() for t in page.locator("a[href*='/tag/']").all_inner_texts()]
        except Exception:
            pass

        # 코드 언어(language-xxx 또는 data-language)
        code_langs: List[str] = []
        try:
            langs = page.eval_on_selector_all(
                "pre code",
                """els => els.map(e => {
                    const cls = (e.className||"").toString();
                    let lang = null;
                    const m = cls.match(/language-([\\w+-]+)/);
                    if (m) lang = m[1].toLowerCase();
                    const dl = e.getAttribute('data-language');
                    if (dl) lang = dl.toLowerCase();
                    return lang;
                })""",
            ) or []
            code_langs = [l for l in langs if l and l != "null"]
        except Exception:
            pass

        # 본문: article -> main -> #root -> body
        text = ""
        try:
            if page.locator("article").count() > 0:
                text = page.locator("article").first.inner_text().strip()
        except Exception:
            pass
        if not text:
            for sel in ["main", "div#root", "body"]:
                try:
                    if page.locator(sel).count() > 0:
                        text = page.locator(sel).first.inner_text().strip()
                        if text:
                            break
                except Exception:
                    continue
        # 그래도 없으면 1회 스크롤 후 재시도
        if not text and (time.perf_counter() - start) < HARD_LIMIT:
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_load_state("networkidle", timeout=2000)
                if page.locator("article").count() > 0:
                    text = page.locator("article").first.inner_text().strip()
            except Exception:
                pass

        # 게시 시각(형태 다양 -> 그대로 저장)
        published = None
        try:
            for s in page.locator("time, span, div").all_inner_texts():
                s2 = s.strip()
                if re.search(r"\d{4}\.\s*\d{1,2}\.\s*\d{1,2}", s2) or ("시간 전" in s2) or ("분 전" in s2) or ("일 전" in s2):
                    published = s2
                    break
        except Exception:
            pass

        browser.close()
        return title, text, sorted(set(code_langs)), tags, published

# 전체 파이프라인
def crawl_all_posts(
    handle: str,
    max_scrolls: int = 200,
    pause_sec: float = 1.0,
    per_post_delay: float = 1.0,
) -> dict:
 
    # 1) 프로필 전체 스크롤 -> 모든 포스트 링크 수집
    # 2) 각 포스트 렌더 -> 메타데이터/본문 추출

    links = render_list_with_playwright(handle, max_scrolls=max_scrolls, pause_sec=pause_sec)
    print(f"[INFO] 링크 수집 완료: {len(links)}개")

    posts = []
    for i, url in enumerate(links, 1):
        try:
            title, text, code_langs, tags, published = render_post_with_playwright(url)

            # 상단 boilerplate 제거
            if text:
                text = re.sub(r"(로그인|팔로우|목록 보기)\s*", " ", text)
                text = re.sub(r"\s{2,}", " ", text).strip()

            posts.append({
                "url": url,
                "title": title or "",
                "tags": tags,
                "published_at": published or "",  # 상대표현일 수 있음
                "updated_at": "",
                "text": text or "",
                "code_langs": code_langs,
                "likes": 0,
                "comments": 0,
                "series": None,
                "content_hash": hashlib.md5(url.encode()).hexdigest(),
            })

            if i % 10 == 0:
                print(f"[INFO] {i}/{len(links)} 수집 중...")
            time.sleep(per_post_delay)  # 매너 딜레이
        except KeyboardInterrupt:
            print("\n[WARN] 사용자 중단 감지. 여기까지 저장합니다.")
            break
        except Exception as ex:
            print("skip:", url, ex)

    return {
        "source": "velog",
        "author": {"handle": handle},
        "posts": posts,
        "schema_version": 1,
    }

if __name__ == "__main__":
    import argparse, os, json

    parser = argparse.ArgumentParser(description="Velog full crawler")
    parser.add_argument("--handle", required=True, help="Velog handle (without @)")
    parser.add_argument("--max-scrolls", type=int, default=220)
    parser.add_argument("--pause", type=float, default=1.0)
    parser.add_argument("--per-post-delay", type=float, default=1.0)
    parser.add_argument("--out", default="out.json", help="output json path")
    parser.add_argument("--resume", action="store_true", help="skip already-scraped URLs from existing out.json")
    args = parser.parse_args()

    # 기존 out.json 로드(증분)
    existing = {"source":"velog","author":{"handle": args.handle},"posts": [], "schema_version":1}
    seen = set()
    if args.resume and os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as f:
            try:
                prev = json.load(f)
                if prev.get("author",{}).get("handle") == args.handle:
                    existing = prev
                    seen = {p["url"] for p in prev.get("posts", [])}
            except Exception:
                pass

    data = crawl_all_posts(
        args.handle, max_scrolls=args.max_scrolls, pause_sec=args.pause, per_post_delay=args.per_post_delay
    )

    # 증분 병합 & 중복 제거
    merged = existing.get("posts", []) + [p for p in data["posts"] if p["url"] not in seen]
    # URL 기준 중복 제거(혹시 두 번 들어온 경우)
    dedup = {}
    for p in merged:
        dedup[p["url"]] = p
    posts = list(dedup.values())

    out = {"source":"velog","author":{"handle": args.handle}, "posts": posts, "schema_version":1}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[DONE] 총 {len(posts)}개 포스트 저장 → {args.out}")

