"""
同程旅行 (ly.com) 景点门票评论抓取工具
目标: https://www.ly.com/scenery/BookSceneryTicket_19987.html
抓取 2025年10月 以前的所有评论

运行方式:
  pip install -r requirements.txt
  python scraper.py                          # 自动Selenium探测 + 抓取
  python scraper.py --no-selenium            # 跳过Selenium，直接探测候选接口
  python scraper.py --api-url "https://..."  # 手动指定接口URL
  python scraper.py --cookies "name=val; ..."
"""

import json
import csv
import time
import logging
import os
import requests
from datetime import datetime
from typing import Optional, Iterator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

CUTOFF_DATE = datetime(2025, 10, 1)
TARGET_URL = "https://www.ly.com/scenery/BookSceneryTicket_19987.html"
PRODUCT_ID = "19987"

# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

def make_session(cookies: Optional[dict] = None) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.6367.119 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": TARGET_URL,
        "Origin": "https://www.ly.com",
    })
    if cookies:
        s.cookies.update(cookies)
    return s


# ---------------------------------------------------------------------------
# Selenium network interception
# ---------------------------------------------------------------------------

# Keywords that mark a network request as a comment/review API call
_COMMENT_KEYWORDS = ("comment", "review", "评论", "score", "ping", "evaluate")


def _is_comment_request(url: str) -> bool:
    low = url.lower()
    return any(kw in low for kw in _COMMENT_KEYWORDS)


def discover_via_seleniumwire(url: str = TARGET_URL) -> Optional[dict]:
    """
    Use seleniumwire to intercept all network requests while loading the
    target page and scrolling to the comment section.
    Returns {"url": <comment_api_url>, "cookies": {...}} or None.
    """
    try:
        from seleniumwire import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
    except ImportError:
        return None

    import shutil
    driver_path = shutil.which("chromedriver")

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1920,1080")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])

    sw_options = {
        "disable_encoding": True,   # get raw response bodies
        "suppress_connection_errors": True,
    }

    service = Service(driver_path) if driver_path else Service()
    driver = webdriver.Chrome(
        service=service, options=opts, seleniumwire_options=sw_options
    )

    captured_requests: list[dict] = []
    try:
        log.info("[Selenium] 打开页面: %s", url)
        driver.get(url)
        time.sleep(3)

        # Scroll to the bottom section where comments are loaded
        for _ in range(8):
            driver.execute_script("window.scrollBy(0, 800)")
            time.sleep(0.8)

        # Try clicking the comment tab if it exists
        try:
            tabs = driver.find_elements(
                By.XPATH,
                '//*[contains(text(),"评论") or contains(text(),"点评") or contains(text(),"好评")]',
            )
            for tab in tabs[:3]:
                try:
                    tab.click()
                    time.sleep(2)
                    break
                except Exception:
                    pass
        except Exception:
            pass

        # Wait for additional XHR to fire after clicking
        time.sleep(2)

        # Collect matching requests from seleniumwire
        for req in driver.requests:
            if req.response is None:
                continue
            req_url = req.url
            if not _is_comment_request(req_url):
                continue
            if req.response.status_code != 200:
                continue
            log.info("[Selenium] 发现评论接口: %s", req_url)
            captured_requests.append({"url": req_url, "headers": dict(req.headers)})

        cookies = {c["name"]: c["value"] for c in driver.get_cookies()}

    finally:
        driver.quit()

    if captured_requests:
        return {"url": captured_requests[0]["url"], "cookies": cookies}
    return {"url": None, "cookies": cookies}


def discover_via_cdp(url: str = TARGET_URL) -> Optional[dict]:
    """
    Fallback: use plain Selenium + Chrome DevTools Protocol performance logs
    to intercept comment API requests.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
    except ImportError:
        log.error("请先安装 selenium: pip install selenium")
        return None

    import shutil
    driver_path = shutil.which("chromedriver")

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1920,1080")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    service = Service(driver_path) if driver_path else Service()
    driver = webdriver.Chrome(service=service, options=opts)
    found_url = None

    try:
        log.info("[CDP] 打开页面: %s", url)
        driver.get(url)
        time.sleep(3)

        for _ in range(8):
            driver.execute_script("window.scrollBy(0, 800)")
            time.sleep(0.8)

        try:
            tabs = driver.find_elements(
                By.XPATH,
                '//*[contains(text(),"评论") or contains(text(),"点评") or contains(text(),"好评")]',
            )
            for tab in tabs[:3]:
                try:
                    tab.click()
                    time.sleep(2)
                    break
                except Exception:
                    pass
        except Exception:
            pass

        time.sleep(2)

        perf_logs = driver.get_log("performance")
        for entry in perf_logs:
            try:
                msg = json.loads(entry["message"])["message"]
                if msg.get("method") != "Network.requestWillBeSent":
                    continue
                req_url = (
                    msg.get("params", {}).get("request", {}).get("url", "")
                )
                if _is_comment_request(req_url):
                    log.info("[CDP] 发现评论接口: %s", req_url)
                    if found_url is None:
                        found_url = req_url
            except Exception:
                pass

        cookies = {c["name"]: c["value"] for c in driver.get_cookies()}

    finally:
        driver.quit()

    return {"url": found_url, "cookies": cookies}


def discover_comment_api(url: str = TARGET_URL) -> Optional[dict]:
    """
    Try seleniumwire first (more reliable), fall back to CDP logs.
    """
    log.info("=== 使用 Selenium 拦截评论接口 ===")

    result = discover_via_seleniumwire(url)
    if result is not None:
        method = "seleniumwire"
    else:
        log.info("seleniumwire 不可用，使用 CDP 日志方式")
        result = discover_via_cdp(url)
        method = "CDP"

    if result and result.get("url"):
        log.info("[%s] 成功捕获接口: %s", method, result["url"])
    else:
        log.warning("[%s] 未捕获到评论接口", method)

    return result


# ---------------------------------------------------------------------------
# Candidate API probe (fallback)
# ---------------------------------------------------------------------------

CANDIDATE_APIS = [
    "https://www.ly.com/api/scenic/comment/getCommentList",
    "https://www.ly.com/scenery/comment/list",
    "https://www.ly.com/api/ticket/comment/list",
    "https://www.ly.com/comment/getCommentList",
    "https://m.ly.com/api/comment/list",
    "https://comment.ly.com/comment/getCommentList",
]

CANDIDATE_PARAMS_LIST = [
    {"scenicId": PRODUCT_ID, "pageIndex": 1, "pageSize": 20, "sortType": 1},
    {"productId": PRODUCT_ID, "pageNum": 1, "pageSize": 20, "sortType": "time"},
    {"id": PRODUCT_ID, "pageIndex": 1, "pageSize": 20},
    {"sceneryId": PRODUCT_ID, "page": 1, "size": 20},
    {"ticketId": PRODUCT_ID, "pageIndex": 1, "pageSize": 20},
]


def probe_api(session: requests.Session) -> Optional[tuple[str, dict]]:
    for api_url in CANDIDATE_APIS:
        for params in CANDIDATE_PARAMS_LIST:
            try:
                resp = session.get(api_url, params=params, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    if extract_comment_list(data):
                        log.info("候选接口命中: %s  参数: %s", api_url, params)
                        return api_url, params
            except Exception:
                pass
            time.sleep(0.3)
    return None


# ---------------------------------------------------------------------------
# Comment extraction + normalization
# ---------------------------------------------------------------------------

def extract_comment_list(data) -> list:
    """Recursively find the first list of comment dicts in any response shape."""
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("data", "Data", "result", "Result", "list", "List",
                "commentList", "CommentList", "items", "records", "reviews"):
        val = data.get(key)
        if val is None:
            continue
        found = extract_comment_list(val)
        if found:
            return found
    return []


def _parse_date(raw) -> Optional[datetime]:
    if not raw:
        return None
    raw = str(raw).strip()
    # Unix timestamp in milliseconds
    if raw.isdigit() and len(raw) == 13:
        return datetime.fromtimestamp(int(raw) / 1000)
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _get_date_field(c: dict) -> str:
    for k in ("commentDate", "createTime", "commentTime", "reviewTime", "time", "date"):
        if c.get(k):
            return str(c[k])
    return ""


def _normalize(raw: dict, dt: Optional[datetime]) -> dict:
    return {
        "product_id": PRODUCT_ID,
        "comment_id": (
            raw.get("commentId") or raw.get("id") or raw.get("reviewId") or ""
        ),
        "user_name": (
            raw.get("userName") or raw.get("nickName")
            or raw.get("userNick") or raw.get("nickname") or ""
        ),
        "score": (
            raw.get("score") or raw.get("rating")
            or raw.get("avgScore") or raw.get("starScore") or ""
        ),
        "content": (
            raw.get("content") or raw.get("commentContent")
            or raw.get("reviewContent") or raw.get("text") or raw.get("comment") or ""
        ),
        "date": dt.strftime("%Y-%m-%d %H:%M:%S") if dt else "",
        "raw_date": _get_date_field(raw),
        "images": json.dumps(
            raw.get("images") or raw.get("imgList") or raw.get("pics") or [],
            ensure_ascii=False,
        ),
        "travel_type": (
            raw.get("travelType") or raw.get("tripType") or raw.get("playType") or ""
        ),
    }


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def fetch_all_comments(
    api_url: str,
    base_params: dict,
    session: requests.Session,
    page_size: int = 20,
) -> Iterator[dict]:
    """Paginate through all results and yield comments before CUTOFF_DATE."""
    page_key = next(
        (k for k in base_params if k in ("pageIndex", "pageNum", "page")), "pageIndex"
    )
    size_key = next(
        (k for k in base_params if k in ("pageSize", "size")), "pageSize"
    )
    page = 1

    while True:
        params = {**base_params, page_key: page, size_key: page_size}
        try:
            resp = session.get(api_url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.error("第%d页请求失败: %s", page, exc)
            break

        comments = extract_comment_list(data)
        if not comments:
            log.info("第%d页无数据，抓取结束。", page)
            break

        log.info("第%d页: 获取 %d 条", page, len(comments))
        yielded = 0
        for c in comments:
            dt = _parse_date(_get_date_field(c))
            if dt is not None and dt >= CUTOFF_DATE:
                log.debug("跳过 %s (≥ 截止日期)", _get_date_field(c))
                continue
            yield _normalize(c, dt)
            yielded += 1

        log.info("第%d页: 符合条件 %d 条", page, yielded)
        page += 1
        time.sleep(0.8)   # polite rate limit


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

FIELDNAMES = [
    "product_id", "comment_id", "user_name", "score",
    "content", "date", "raw_date", "images", "travel_type",
]


def save_csv(records: list, path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        w.writeheader()
        w.writerows(records)
    log.info("CSV: %s  (%d 条)", path, len(records))


def save_json(records: list, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    log.info("JSON: %s  (%d 条)", path, len(records))


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(
    output_dir: str = "output",
    use_selenium: bool = True,
    manual_api_url: Optional[str] = None,
    manual_cookies: Optional[str] = None,
) -> list:
    os.makedirs(output_dir, exist_ok=True)

    # Parse manual cookies
    cookies: dict = {}
    if manual_cookies:
        for part in manual_cookies.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                cookies[k.strip()] = v.strip()

    api_url = manual_api_url
    api_params: dict = {}

    # Step 1: Selenium auto-discovery
    if not api_url and use_selenium:
        info = discover_comment_api(TARGET_URL)
        if info:
            cookies.update(info.get("cookies", {}))
            if info.get("url"):
                api_url = info["url"]

    session = make_session(cookies)

    # Step 2: Probe candidate endpoints
    if not api_url:
        log.info("=== 探测候选接口 ===")
        result = probe_api(session)
        if result:
            api_url, api_params = result
        else:
            log.error(
                "\n所有方法均失败。请手动操作:\n"
                "1. 用Chrome打开: %s\n"
                "2. 按F12 → Network → 筛选 'comment' 或 'review'\n"
                "3. 滚动到评论区，找到加载评论的请求\n"
                "4. 复制请求URL，用 --api-url 参数传入\n"
                "5. 复制Cookie，用 --cookies 参数传入",
                TARGET_URL,
            )
            return []

    # Step 3: Collect all comments before cutoff
    log.info("=== 开始抓取 (截止 %s) ===", CUTOFF_DATE.date())
    all_records = list(fetch_all_comments(api_url, api_params, session))
    log.info("共抓取 %d 条评论", len(all_records))

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_csv(all_records, os.path.join(output_dir, f"comments_{ts}.csv"))
    save_json(all_records, os.path.join(output_dir, f"comments_{ts}.json"))
    return all_records


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="同程旅行景点门票评论抓取（截止2025年10月）\n"
                    f"目标: {TARGET_URL}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--no-selenium", action="store_true",
        help="跳过 Selenium 自动探测，直接尝试候选接口",
    )
    parser.add_argument(
        "--api-url",
        help="手动指定评论接口URL（从浏览器开发者工具中获取）",
    )
    parser.add_argument(
        "--cookies",
        help='浏览器 Cookie 字符串，格式: "name1=val1; name2=val2"',
    )
    parser.add_argument(
        "--output-dir", default="output",
        help="输出目录（默认: output）",
    )
    args = parser.parse_args()

    records = run(
        output_dir=args.output_dir,
        use_selenium=not args.no_selenium,
        manual_api_url=args.api_url,
        manual_cookies=args.cookies,
    )
    print(f"\n抓取完成，共 {len(records)} 条评论（2025年10月前）")
