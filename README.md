# 同程旅行评论抓取工具

抓取同程旅行（ly.com）上 **2025年10月以前** 的所有酒店/景点评论，保存为 CSV 和/或 JSON。

## 安装

```bash
pip install -r requirements.txt
```

## 使用方法

### 抓取酒店评论

```bash
python scraper.py --hotel-ids 12345 67890
```

### 抓取景点评论

```bash
python scraper.py --scenic-ids 11111 22222
```

### 同时抓取酒店和景点

```bash
python scraper.py --hotel-ids 12345 --scenic-ids 11111 --output-dir results --format both
```

### 全部参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--hotel-ids` | 酒店ID列表（空格分隔） | 无 |
| `--scenic-ids` | 景点ID列表（空格分隔） | 无 |
| `--output-dir` | 输出目录 | `output` |
| `--format` | 输出格式：`csv` / `json` / `both` | `both` |

## 如何获取酒店/景点ID

1. 在浏览器打开同程旅行酒店或景点详情页
2. URL 中的数字即为 ID，例如：
   - `https://hotels.ly.com/hotel/detail/12345` → 酒店ID `12345`
   - `https://www.ly.com/scenic/detail/11111` → 景点ID `11111`

## 输出格式

结果保存在 `output/` 目录，文件名含时间戳：

- `tongcheng_comments_YYYYMMDD_HHMMSS.csv`
- `tongcheng_comments_YYYYMMDD_HHMMSS.json`

### 字段说明

| 字段 | 说明 |
|------|------|
| `type` | 类型：`hotel` 或 `scenic` |
| `hotel_id` / `scenic_id` | 酒店或景点ID |
| `comment_id` | 评论ID |
| `user_name` | 用户昵称 |
| `score` | 评分 |
| `content` | 评论内容 |
| `date` | 评论时间（格式化） |
| `raw_date` | 原始时间字符串 |
| `room_type` | 房型（仅酒店） |

## 注意事项

- 工具已内置 0.8 秒请求间隔，避免对服务器造成压力
- 仅抓取 2025-10-01 之前发布的评论
- 如遇到 403 或反爬拦截，可在 `scraper.py` 的 `HEADERS` 中添加 Cookie
