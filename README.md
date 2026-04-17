# 同程旅行小程序评论抓取

**目标景点（微信PC版小程序）：**
- 凤凰古城
- 矮寨奇观旅游区-矮寨大桥
- 德夯峡谷景区
- 芙蓉镇

**截止日期：** 2025年10月前的所有评论

---

## 工作原理

```
微信PC小程序 → mitmproxy本地代理 → intercept.py 捕获评论接口
                                           ↓
                              scraper.py 自动分页抓取所有评论
                                           ↓
                              output/ 目录保存 CSV + JSON
```

---

## 操作步骤（全在电脑上）

### 第一步：安装依赖

```bash
pip install -r requirements.txt
```

### 第二步：一键启动代理 + 拦截

```bash
python proxy_setup.py start
```

脚本会自动：
1. 备份当前系统代理设置
2. 设置系统代理到 `127.0.0.1:8888`
3. 自动安装 mitmproxy CA 证书到系统信任列表
4. 启动 mitmproxy 拦截脚本

> **Windows** 需要以管理员身份运行（右键 → 以管理员身份运行终端）  
> **macOS** 安装证书时会要求输入系统密码

### 第三步：在微信PC版中操作

打开微信 → 搜索「同程旅行」小程序，依次进入每个景点：

1. **凤凰古城** → 点击「评论/点评」标签 → 向下滚动 2~3 页
2. **矮寨奇观旅游区-矮寨大桥** → 同上
3. **德夯峡谷景区** → 同上
4. **芙蓉镇** → 同上

终端会打印捕获到的接口，例如：
```
✓ 捕获: [凤凰古城] https://api.ly.com/scenic/comment/list
  方法: GET
  参数: {'scenicId': '12345', 'pageIndex': '1', 'pageSize': '20'}
```

4个景点都捕获到后，按 `Ctrl+C` 结束，系统代理自动还原。

### 第四步：批量抓取评论

```bash
python scraper.py
```

自动读取 `captured_apis.json`，逐景点分页拉取所有 2025-10-01 之前的评论。

---

## 输出文件

```
output/
├── comments_20241017_143022.csv        # 全部评论（汇总）
├── comments_20241017_143022.json
├── 凤凰古城_20241017_143022.csv
├── 矮寨大桥_20241017_143022.csv
├── 德夯峡谷景区_20241017_143022.csv
└── 芙蓉镇_20241017_143022.csv
```

### 字段说明

| 字段 | 说明 |
|------|------|
| `scenic_name` | 景点名称 |
| `scenic_id` | 景点ID |
| `comment_id` | 评论ID |
| `user_name` | 用户昵称 |
| `score` | 评分 |
| `content` | 评论内容 |
| `date` | 格式化时间 |
| `raw_date` | 原始时间字符串 |
| `images` | 评论图片列表（JSON数组） |
| `travel_type` | 出行类型 |
| `reply` | 商家回复 |

---

## 常见问题

**Q: 终端没有捕获到任何请求？**  
A: 微信小程序可能不走系统代理。解决方法：
1. 完全退出微信，重新打开（让微信读取新的代理设置）
2. 或使用 [Proxifier](https://www.proxifier.com/) 强制微信走代理

**Q: 捕获到请求但响应是乱码？**  
A: CA 证书未正确安装，参考第二步手动安装：
- Windows: `%USERPROFILE%\.mitmproxy\mitmproxy-ca-cert.p12` → 双击 → 安装到「受信任的根证书颁发机构」
- macOS: `~/.mitmproxy/mitmproxy-ca-cert.pem` → 双击加入钥匙串 → 设为「始终信任」

**Q: scraper.py 运行后提示「未找到已捕获的接口」？**  
A: 第三步还没有操作小程序，`captured_apis.json` 还是空的，按步骤操作后重试。

**Q: 还原代理失败？**  
A: 手动运行 `python proxy_setup.py stop`，或在系统设置里直接关闭代理。
