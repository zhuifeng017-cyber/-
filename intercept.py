"""
intercept.py —— mitmproxy 拦截脚本
自动捕获同程旅行小程序的评论接口请求，保存到 captured_apis.json。

启动方式（通过 proxy_setup.py 自动调用）:
  python proxy_setup.py start

或手动启动:
  mitmdump -s intercept.py --listen-port 8888
"""

import json
import os
import re
from urllib.parse import urlparse, parse_qs
from mitmproxy import http

SAVE_FILE = "captured_apis.json"

# 识别评论接口的关键词（URL中出现任意一个则视为评论接口）
COMMENT_KEYWORDS = [
    "comment", "review", "评论", "evaluate",
    "score", "appraise", "remark", "eval",
    "feedback", "rating", "ping",
]

# 目标域名（只拦截同程相关域名）
TARGET_DOMAINS = (
    "ly.com",
    "tongcheng.com",
    "tctravel.com",
    "lyfz.net",
    "lyhd.com",
)

# 景点名称 → 关键词映射（通过URL参数或响应内容识别是哪个景点）
SCENIC_KEYWORDS = {
    "凤凰古城":           ["fenghuang", "凤凰", "phoenix"],
    "矮寨大桥":           ["aizhai", "矮寨", "qiaoguanTunnel"],
    "德夯峡谷景区":       ["dehang", "德夯", "gorge"],
    "芙蓉镇":             ["furong", "芙蓉"],
}

# 已捕获的接口（key = URL去掉query string）
captured: dict = {}
if os.path.exists(SAVE_FILE):
    with open(SAVE_FILE, "r", encoding="utf-8") as f:
        try:
            captured = json.load(f)
        except json.JSONDecodeError:
            captured = {}


def _is_target_domain(host: str) -> bool:
    return any(d in host for d in TARGET_DOMAINS)


def _is_comment_url(url: str) -> bool:
    low = url.lower()
    return any(kw in low for kw in COMMENT_KEYWORDS)


def _guess_scenic_name(url: str, params: dict, body: dict) -> str:
    """Try to identify which scenic spot this request belongs to."""
    combined_text = (url + json.dumps(params, ensure_ascii=False)
                     + json.dumps(body, ensure_ascii=False)).lower()
    for name, keywords in SCENIC_KEYWORDS.items():
        if any(kw.lower() in combined_text for kw in keywords):
            return name
    return "未知景点"


def _extract_params(flow: http.HTTPFlow) -> tuple[dict, dict]:
    params = dict(flow.request.query)
    body = {}
    if flow.request.method.upper() == "POST":
        ct = flow.request.headers.get("content-type", "")
        try:
            if "json" in ct:
                body = json.loads(flow.request.content)
            elif "form" in ct:
                from urllib.parse import parse_qs
                body = {k: v[0] for k, v in parse_qs(
                    flow.request.text).items()}
        except Exception:
            pass
    return params, body


def _save():
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        json.dump(captured, f, ensure_ascii=False, indent=2)


def request(flow: http.HTTPFlow) -> None:
    host = flow.request.host
    url  = flow.request.pretty_url

    if not _is_target_domain(host):
        return
    if not _is_comment_url(url):
        return

    params, body = _extract_params(flow)
    scenic_name  = _guess_scenic_name(url, params, body)

    # Parse cookies
    cookies_raw = flow.request.headers.get("cookie", "")
    cookies = {}
    for part in cookies_raw.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()

    # Keep headers useful for replay (drop hop-by-hop headers)
    skip = {"cookie", "host", "content-length", "transfer-encoding",
            "connection", "proxy-connection"}
    headers = {k: v for k, v in flow.request.headers.items()
               if k.lower() not in skip}

    key = url.split("?")[0]

    if key not in captured:
        entry = {
            "scenic_name": scenic_name,
            "url":         url,
            "base_url":    key,
            "method":      flow.request.method.upper(),
            "params":      params,
            "body":        body,
            "cookies":     cookies,
            "headers":     headers,
        }
        captured[key] = entry
        _save()
        print(f"\n✓ 捕获: [{scenic_name}] {key}")
        print(f"  方法: {entry['method']}")
        print(f"  参数: {params or body}")
    else:
        # Update cookies/headers in case they changed
        captured[key]["cookies"].update(cookies)
        _save()


def response(flow: http.HTTPFlow) -> None:
    host = flow.request.host
    url  = flow.request.pretty_url

    if not _is_target_domain(host):
        return
    if not _is_comment_url(url):
        return

    key = url.split("?")[0]
    if key not in captured:
        return

    if flow.response.status_code != 200:
        return

    # Save a sample of the response to help with field mapping
    try:
        data = json.loads(flow.response.content)
        captured[key]["sample_response"] = data
        _save()
        print(f"  响应已保存（状态: {flow.response.status_code}）")
    except Exception:
        pass
