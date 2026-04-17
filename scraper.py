"""
同程旅行小程序 —— 景点评论批量抓取
目标景点:
  - 凤凰古城
  - 矮寨奇观旅游区-矮寨大桥
  - 德夯峡谷景区
  - 芙蓉镇
截止日期: 2025-10-01

使用方式:
  第一步: 用 mitmproxy 拦截小程序流量，得到 captured_apis.json
          mitmproxy -s intercept.py --listen-port 8888
  第二步: 运行本脚本
          python scraper.py
  或者手动指定接口:
          python scraper.py --api-url "https://..." --scenic-id "12345" --name "凤凰古城"
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
CAPTURED_FILE = "captured_apis.json"

# ---------------------------------------------------------------------------
# 目标景点配置（scenic_id 在抓包后填入，或由脚本自动识别）
# ---------------------------------------------------------------------------

TARGETS = [
    {"name": "凤凰古城",           "scenic_id": None},
    {"name": "矮寨大桥",           "scenic_id": None},
    {"name": "德夯峡谷景区",       "scenic_id": None},
    {"name": "芙蓉镇",             "scenic_id": None},
]


# ---------------------------------------------------------------------------
# Load captured API info from intercept.py output
# ---------------------------------------------------------------------------

def load_captured_apis(path: str = CAPTURED_FILE) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return list(data.values()) if isinstance(data, dict) else data


def _extract_scenic_id(entry: dict) -> Optional[str]:
    """Try to pull a scenic/product ID out of request params or body."""
    combined = {**entry.get("params", {}), **entry.get("body", {})}
    for key in ("scenicId", "productId", "id", "sceneryId", "ticketId",
                "attractionId", "poiId", "sid"):
        if combined.get(key):
            return str(combined[key])
    # Try to find a number in the URL path
    import re
    m = re.search(r"/(\d{4,})", entry.get("url", ""))
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------

def make_session(cookies: Optional[dict] = None,
                 extra_headers: Optional[dict] = None) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Mobile Safari/537.36 "
            "MicroMessenger/8.0.47 MiniProgramEnv/android"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    if extra_headers:
        s.headers.update(extra_headers)
    if cookies:
        s.cookies.update(cookies)
    return s


# ---------------------------------------------------------------------------
# Comment list extraction (handles any response envelope shape)
# ---------------------------------------------------------------------------

def extract_list(data) -> list:
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("data", "Data", "result", "Result", "list", "List",
                "commentList", "CommentList", "items", "records",
                "reviews", "evalList", "appraises"):
        val = data.get(key)
        if val is None:
            continue
        found = extract_list(val)
        if found:
            return found
    return []


def _parse_date(raw) -> Optional[datetime]:
    if not raw:
        return None
    raw = str(raw).strip()
    if raw.isdigit() and len(raw) == 13:           # ms timestamp
        return datetime.fromtimestamp(int(raw) / 1000)
    if raw.isdigit() and len(raw) == 10:           # s timestamp
        return datetime.fromtimestamp(int(raw))
    for fmt in (
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
        "%Y/%m/%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d",
    ):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _date_field(c: dict) -> str:
    for k in ("commentDate", "createTime", "commentTime",
              "reviewTime", "time", "date", "publishTime"):
        if c.get(k):
            return str(c[k])
    return ""


def _normalize(raw: dict, name: str, scenic_id: str,
               dt: Optional[datetime]) -> dict:
    return {
        "scenic_name":  name,
        "scenic_id":    scenic_id,
        "comment_id":   (raw.get("commentId") or raw.get("id")
                         or raw.get("reviewId") or ""),
        "user_name":    (raw.get("userName") or raw.get("nickName")
                         or raw.get("userNick") or raw.get("nickname") or ""),
        "score":        (raw.get("score") or raw.get("rating")
                         or raw.get("avgScore") or raw.get("starScore") or ""),
        "content":      (raw.get("content") or raw.get("commentContent")
                         or raw.get("reviewContent") or raw.get("text")
                         or raw.get("comment") or ""),
        "date":         dt.strftime("%Y-%m-%d %H:%M:%S") if dt else "",
        "raw_date":     _date_field(raw),
        "images":       json.dumps(
                            raw.get("images") or raw.get("imgList")
                            or raw.get("pics") or [],
                            ensure_ascii=False),
        "travel_type":  (raw.get("travelType") or raw.get("tripType")
                         or raw.get("playType") or ""),
        "reply":        (raw.get("replyContent") or raw.get("reply") or ""),
    }


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def _find_page_key(params: dict, body: dict) -> tuple[str, str]:
    combined = {**params, **body}
    page_k = next(
        (k for k in combined if k in ("pageIndex", "pageNum", "page", "pageNo")),
        "pageIndex",
    )
    size_k = next(
        (k for k in combined if k in ("pageSize", "size", "limit", "num")),
        "pageSize",
    )
    return page_k, size_k


def fetch_comments(
    entry: dict,
    scenic_name: str,
    scenic_id: str,
    session: requests.Session,
    page_size: int = 20,
) -> Iterator[dict]:
    api_url = entry["url"].split("?")[0]
    base_params = dict(entry.get("params", {}))
    base_body   = dict(entry.get("body", {}))
    method = entry.get("method", "GET").upper()

    page_k, size_k = _find_page_key(base_params, base_body)
    page = 1

    while True:
        if method == "POST":
            payload = {**base_body, page_k: page, size_k: page_size}
            try:
                resp = session.post(api_url, json=payload, timeout=15)
                resp.raise_for_status()
            except Exception as exc:
                log.error("[%s] 第%d页 POST 失败: %s", scenic_name, page, exc)
                break
        else:
            params = {**base_params, page_k: page, size_k: page_size}
            try:
                resp = session.get(api_url, params=params, timeout=15)
                resp.raise_for_status()
            except Exception as exc:
                log.error("[%s] 第%d页 GET 失败: %s", scenic_name, page, exc)
                break

        try:
            data = resp.json()
        except Exception:
            log.error("[%s] 第%d页响应非JSON", scenic_name, page)
            break

        comments = extract_list(data)
        if not comments:
            log.info("[%s] 第%d页无数据，结束。", scenic_name, page)
            break

        log.info("[%s] 第%d页 %d 条", scenic_name, page, len(comments))
        yielded = 0
        for c in comments:
            dt = _parse_date(_date_field(c))
            if dt is not None and dt >= CUTOFF_DATE:
                log.debug("[%s] 跳过 %s", scenic_name, _date_field(c))
                continue
            yield _normalize(c, scenic_name, scenic_id, dt)
            yielded += 1

        log.info("[%s] 第%d页符合条件 %d 条", scenic_name, page, yielded)
        page += 1
        time.sleep(0.8)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

FIELDNAMES = [
    "scenic_name", "scenic_id", "comment_id", "user_name",
    "score", "content", "date", "raw_date",
    "images", "travel_type", "reply",
]


def save_csv(records: list, path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        w.writeheader()
        w.writerows(records)
    log.info("CSV 保存: %s  (%d 条)", path, len(records))


def save_json(records: list, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    log.info("JSON 保存: %s  (%d 条)", path, len(records))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    captured_file: str = CAPTURED_FILE,
    output_dir: str = "output",
    manual_entries: Optional[list[dict]] = None,
) -> list:
    os.makedirs(output_dir, exist_ok=True)
    entries = manual_entries or load_captured_apis(captured_file)

    if not entries:
        log.error(
            "\n未找到已捕获的接口信息 (%s)。\n\n"
            "请先用 mitmproxy 抓包:\n"
            "  1. pip install mitmproxy\n"
            "  2. mitmproxy -s intercept.py --listen-port 8888\n"
            "  3. 手机Wi-Fi设置代理 → 电脑IP:8888\n"
            "  4. 安装 mitmproxy CA 证书 (http://mitm.it)\n"
            "  5. 打开同程旅行小程序，进入每个景点的评论页并滚动\n"
            "  6. captured_apis.json 会自动生成\n"
            "  7. 再次运行 python scraper.py",
            captured_file,
        )
        return []

    log.info("加载 %d 个已捕获接口", len(entries))
    all_records: list = []

    for entry in entries:
        scenic_id = _extract_scenic_id(entry)
        scenic_name = entry.get("scenic_name", entry.get("url", "unknown"))

        if not scenic_id:
            log.warning("无法从 %s 提取景点ID，跳过", entry.get("url"))
            continue

        session = make_session(
            cookies=entry.get("cookies"),
            extra_headers=entry.get("headers"),
        )

        log.info("=== 开始抓取: %s (ID: %s) ===", scenic_name, scenic_id)
        records = list(fetch_comments(entry, scenic_name, scenic_id, session))
        log.info("=== %s 共 %d 条 ===", scenic_name, len(records))
        all_records.extend(records)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_csv(all_records, os.path.join(output_dir, f"comments_{ts}.csv"))
    save_json(all_records, os.path.join(output_dir, f"comments_{ts}.json"))

    # Per-scenic CSV
    from itertools import groupby
    key = lambda r: r["scenic_name"]
    for name, group in groupby(sorted(all_records, key=key), key=key):
        grp = list(group)
        safe = name.replace("/", "_").replace(" ", "_")
        save_csv(grp, os.path.join(output_dir, f"{safe}_{ts}.csv"))

    return all_records


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "同程旅行小程序景点评论抓取（截止2025年10月）\n"
            "景点: 凤凰古城 / 矮寨大桥 / 德夯峡谷 / 芙蓉镇"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--captured", default=CAPTURED_FILE,
        help=f"mitmproxy 捕获的接口文件（默认: {CAPTURED_FILE}）",
    )
    parser.add_argument(
        "--output-dir", default="output",
        help="输出目录（默认: output）",
    )
    # Manual override
    parser.add_argument("--api-url",   help="手动指定接口URL")
    parser.add_argument("--scenic-id", help="手动指定景点ID")
    parser.add_argument("--name",      help="景点名称（配合 --api-url 使用）")
    parser.add_argument("--cookies",   help='Cookie字符串: "name=val; ..."')
    args = parser.parse_args()

    manual = None
    if args.api_url:
        cookies = {}
        if args.cookies:
            for part in args.cookies.split(";"):
                if "=" in part:
                    k, v = part.strip().split("=", 1)
                    cookies[k.strip()] = v.strip()
        manual = [{
            "url": args.api_url,
            "method": "GET",
            "params": {"scenicId": args.scenic_id} if args.scenic_id else {},
            "body": {},
            "cookies": cookies,
            "headers": {},
            "scenic_name": args.name or args.scenic_id or "unknown",
        }]

    records = run(
        captured_file=args.captured,
        output_dir=args.output_dir,
        manual_entries=manual,
    )
    print(f"\n抓取完成，共 {len(records)} 条评论（2025年10月前）")
