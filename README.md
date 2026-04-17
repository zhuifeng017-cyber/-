# 同程旅行评论抓取工具

目标页面: `https://www.ly.com/scenery/BookSceneryTicket_19987.html`  
抓取所有 **2025年10月以前** 的评论，保存为 CSV 和 JSON。

## 安装依赖

```bash
pip install -r requirements.txt
```

还需要安装 [ChromeDriver](https://chromedriver.chromium.org/)，版本需与本机 Chrome 匹配：

```bash
# Ubuntu/Debian
apt install chromium-driver

# macOS
brew install chromedriver

# 或手动下载放入 PATH
```

## 使用方法

### 方式一：全自动（推荐）

Selenium 自动打开页面、拦截评论接口、批量抓取：

```bash
python scraper.py
```

### 方式二：手动指定接口

若自动探测失败，手动在浏览器中找到评论接口：

1. 用 Chrome 打开目标页面
2. 按 `F12` → `Network` 选项卡 → 筛选框输入 `comment`
3. 滚动到页面评论区，触发加载
4. 复制评论请求的 URL 和 Cookie

```bash
python scraper.py \
  --api-url "https://www.ly.com/api/scenic/comment/getCommentList?scenicId=19987" \
  --cookies "sessionId=xxx; token=yyy"
```

### 方式三：跳过 Selenium

```bash
python scraper.py --no-selenium
```

## 参数说明

| 参数 | 说明 |
|------|------|
| `--no-selenium` | 跳过 Selenium，直接探测候选接口 |
| `--api-url` | 手动指定评论接口 URL |
| `--cookies` | 浏览器 Cookie 字符串 |
| `--output-dir` | 输出目录（默认: `output`） |

## 输出格式

结果保存在 `output/` 目录：

- `comments_YYYYMMDD_HHMMSS.csv`
- `comments_YYYYMMDD_HHMMSS.json`

### 字段说明

| 字段 | 说明 |
|------|------|
| `product_id` | 景点ID (19987) |
| `comment_id` | 评论ID |
| `user_name` | 用户昵称 |
| `score` | 评分 |
| `content` | 评论内容 |
| `date` | 格式化时间 |
| `raw_date` | 原始时间字符串 |
| `images` | 评论图片列表 (JSON) |
| `travel_type` | 出行类型 |

## 工作原理

```
打开页面
  ↓
seleniumwire 拦截所有 XHR/fetch 请求
  ↓
找到含 "comment"/"review" 的接口 URL
  ↓
用 requests 分页抓取所有评论
  ↓
过滤 date < 2025-10-01 的评论
  ↓
保存 CSV + JSON
```
