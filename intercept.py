"""
mitmproxy 拦截脚本 (intercept.py)
在手机上配置代理后，打开同程旅行小程序的景点评论页，
本脚本自动捕获评论接口并保存到 captured_apis.json。

启动方式:
  mitmproxy -s intercept.py --listen-port 8888
  或
  mitmdump -s intercept.py --listen-port 8888
"""

import json
import os
import re
from mitmproxy import http

# 目标景点关键词（用于识别是哪个景点的请求）
SCENIC_NAMES = {
    "fenghuang":  "凤凰古城",
    "aizhai":     "矮寨大桥",
    "dehang":     "德夯峡谷",
    "furong":     "芙蓉镇",
}

# 识别评论接口的关键词
COMMENT_KEYWORDS = [
    "comment", "review", "评论", "ping", "evaluate",
    "score", "appraise", "remark",
]

SAVE_FILE = "captured_apis.json"

captured: dict = {}
if os.path.exists(SAVE_FILE):
    with open(SAVE_FILE, "r", encoding="utf-8") as f:
        captured = json.load(f)


def _is_comment_url(url: str) -> bool:
    low = url.lower()
    return any(kw in low for kw in COMMENT_KEYWORDS)


def _save():
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        json.dump(captured, f, ensure_ascii=False, indent=2)


def request(flow: http.HTTPFlow) -> None:
    url = flow.request.pretty_url
    if not _is_comment_url(url):
        return

    # Only capture Tongcheng / ly.com domains
    host = flow.request.host
    if not any(d in host for d in ("ly.com", "tongcheng.com", "tctravel.com")):
        return

    headers = dict(flow.request.headers)
    cookies_raw = headers.get("cookie", "")
    cookies = {}
    for part in cookies_raw.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()

    params = dict(flow.request.query)
    body = {}
    if flow.request.method == "POST":
        try:
            body = json.loads(flow.request.content)
        except Exception:
            try:
                from urllib.parse import parse_qs
                body = {k: v[0] for k, v in parse_qs(flow.request.text).items()}
            except Exception:
                pass

    entry = {
        "url": url,
        "method": flow.request.method,
        "params": params,
        "body": body,
        "cookies": cookies,
        "headers": {
            k: v for k, v in headers.items()
            if k.lower() not in ("cookie", "host")
        },
    }

    key = url.split("?")[0]
    if key not in captured:
        captured[key] = entry
        _save()
        print(f"\n[捕获] {url}")
        print(f"       参数: {params or body}")


def response(flow: http.HTTPFlow) -> None:
    url = flow.request.pretty_url
    if not _is_comment_url(url):
        return
    host = flow.request.host
    if not any(d in host for d in ("ly.com", "tongcheng.com", "tctravel.com")):
        return

    key = url.split("?")[0]
    if key in captured:
        try:
            data = json.loads(flow.response.content)
            captured[key]["sample_response"] = data
            _save()
        except Exception:
            pass
