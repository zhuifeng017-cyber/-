# 同程旅行小程序评论抓取

**目标景点（微信小程序）：**
- 凤凰古城
- 矮寨奇观旅游区-矮寨大桥
- 德夯峡谷景区
- 芙蓉镇

**截止日期：** 2025年10月前的所有评论

---

## 工作原理

小程序无法直接爬取，需要通过 **mitmproxy 中间人代理** 拦截 HTTPS 请求，
获取评论接口后再批量抓取。

```
手机小程序  →  mitmproxy代理（电脑）  →  intercept.py 保存接口信息
                                              ↓
                                        scraper.py 批量抓取所有评论
```

---

## 操作步骤

### 第一步：安装依赖

```bash
pip install -r requirements.txt
```

还需要安装 mitmproxy（如未包含在pip中）：
```bash
# macOS
brew install mitmproxy

# Windows: 下载安装包 https://mitmproxy.org/
```

### 第二步：启动拦截代理

```bash
mitmproxy -s intercept.py --listen-port 8888
# 或使用无界面模式
mitmdump -s intercept.py --listen-port 8888
```

### 第三步：手机配置代理

1. 手机和电脑连同一个 Wi-Fi
2. 手机 Wi-Fi 设置 → 手动代理 → 填入电脑IP和端口 `8888`
3. 手机浏览器打开 `http://mitm.it`，安装 mitmproxy CA 证书
4. **iOS**: 安装后还需在「设置 → 通用 → 关于本机 → 证书信任设置」中启用
5. **Android**: 安装后在「设置 → 安全 → 用户凭据」中信任

### 第四步：触发小程序评论加载

打开微信，进入同程旅行小程序，依次进入每个景点：
1. **凤凰古城** → 滑动到评论区，向下滚动2-3页
2. **矮寨奇观旅游区-矮寨大桥** → 同上
3. **德夯峡谷景区** → 同上
4. **芙蓉镇** → 同上

此时电脑终端会显示捕获到的评论接口，并自动保存到 `captured_apis.json`。

### 第五步：批量抓取评论

```bash
python scraper.py
```

结果保存在 `output/` 目录：

```
output/
├── comments_20241017_143022.csv        # 全部评论（汇总）
├── comments_20241017_143022.json
├── 凤凰古城_20241017_143022.csv       # 每个景点单独一份
├── 矮寨大桥_20241017_143022.csv
├── 德夯峡谷景区_20241017_143022.csv
└── 芙蓉镇_20241017_143022.csv
```

---

## 手动指定接口（如自动捕获失败）

如果你已经用 Charles / Fiddler / 浏览器DevTools 找到了接口 URL：

```bash
python scraper.py \
  --api-url "https://api.ly.com/scenic/comment/list" \
  --scenic-id "12345" \
  --name "凤凰古城" \
  --cookies "sessionId=xxx; token=yyy"
```

---

## 输出字段说明

| 字段 | 说明 |
|------|------|
| `scenic_name` | 景点名称 |
| `scenic_id` | 景点ID |
| `comment_id` | 评论ID |
| `user_name` | 用户昵称 |
| `score` | 评分 |
| `content` | 评论内容 |
| `date` | 格式化时间（YYYY-MM-DD HH:MM:SS） |
| `raw_date` | 原始时间字符串 |
| `images` | 评论图片列表（JSON数组） |
| `travel_type` | 出行类型 |
| `reply` | 商家回复 |

---

## 注意事项

- 脚本会自动过滤 `date >= 2025-10-01` 的评论
- 每页请求间隔 0.8 秒，避免频率过高
- 关闭代理后记得恢复手机 Wi-Fi 设置
