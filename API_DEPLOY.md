# 注音 API 免费上线指南（给面试官测试用）

把项目的**注音核心功能**单独抽成一个轻量 API，跑在一台免费的服务器/隧道上，面试官就能直接：

> 向我传一段日文 → 我返回每个词、每个字的平假名读音。

轻量 API 只依赖 `flask + fugashi + unidic-lite`（约 50MB 词典），不含数据库/后台抓取/TTS，因此部署快、冷启动快。

---

## 0. 接口长什么样

### 请求

```
POST /api/furigana
Content-Type: application/json

{"text": "今日は良い天気ですね。六千人が競争する。"}
```

### 响应（三档粒度）

```json
{
  "text": "今日は良い天気ですね。六千人が競争する。",
  "segments": [
    {"s": "今日", "r": "きょう"},
    {"s": "は",   "r": null},
    {"s": "良い", "r": "よい"}
  ],
  "words": [
    {"word": "今日",   "reading": "きょう"},
    {"word": "競争",   "reading": "きょうそう"}
  ],
  "chars": [
    {"char": "今", "reading": "きょう"},
    {"char": "競", "reading": "きょう"},
    {"char": "争", "reading": "そう"}
  ]
}
```

- `segments`：逐片段读音（假名片段 `r` 为 null）
- `words`：词读音（整词）
- `chars`：逐字读音（字素对齐，核心亮点）

另有 `POST /api/annotate`，返回完整 token 结构（兼容主程序）。

### curl 示例

```bash
curl -X POST https://你的网址/api/furigana \
  -H "Content-Type: application/json" \
  -d '{"text":"今日は良い天気ですね。"}'
```

---

## 方案 A：Cloudflare Tunnel（推荐 ⭐ 零部署、即时、完全免费）

**最适合「面试演示」场景**：不用注册付费、不用推代码、不用等构建，本机一条命令就有公网网址，面试官立刻能测。

> 原理：本地电脑跑 API，Cloudflare 免费隧道把本机端口映射成一个 `https://xxx.trycloudflare.com` 公网地址。电脑保持开机、开着隧道即可。

### 第 1 步：本地启动 API

```powershell
cd d:\10_Workspace\kanji-tool
.\venv\Scripts\python.exe furigana_api.py
```

看到 `Running on http://0.0.0.0:5000` 即成功。浏览器打开 `http://localhost:5000` 有可视化测试页。

### 第 2 步：开一条 Cloudflare 隧道

方式一（Windows 用 winget 装）：

```powershell
winget install --id Cloudflare.cloudflared
cloudflared tunnel --url http://localhost:5000
```

方式二（直接下载 exe，免安装）：到 https://github.com/cloudflare/cloudflared/releases 下载 `cloudflared-windows-amd64.exe`，重命名成 `cloudflared.exe` 后：

```powershell
.\cloudflared.exe tunnel --url http://localhost:5000
```

启动后会打印一行：

```
Your quick Tunnel has been created! Visit it at https://xxxx-xxxx-xxxx.trycloudflare.com
```

把这个网址发给面试官即可。面试官用浏览器打开首页，或：

```bash
curl -X POST https://xxxx-xxxx-xxxx.trycloudflare.com/api/furigana \
  -H "Content-Type: application/json" -d '{"text":"学校に行った。"}'
```

### 注意

- 该网址**每次启动隧道会变**；想固定网址需绑域名（免费但要多几步），面试演示用临时网址完全够。
- 电脑关机/关隧道后网址失效，重新跑一次就又能用了。

---

## 方案 B：Render（常驻 ⭐ 网址固定，免费层有冷启动）

想给一个**固定网址、随时可访问**的 API，用 Render 免费层（有 15 分钟无访问休眠，下次请求等约 50 秒冷启动，个人演示够用）。

### 第 1 步：推代码到 GitHub

新建一个仓库，只推这几个文件即可（其余文件可不管）：

```
furigana.py          ← 注音引擎（核心）
furigana_api.py      ← 轻量 API
requirements_api.txt ← 精简依赖
Dockerfile.api       ← 轻量 Docker 构建
```

### 第 2 步：Render 建 Web Service

1. 打开 https://render.com → Sign in with GitHub
2. New + → Web Service → 选你的仓库 → Connect
3. 关键配置（其余默认）：

| 配置项 | 值 |
|---|---|
| Runtime | Docker |
| Dockerfile Path | `Dockerfile.api` |
| Instance Type | **Free** |

> 或不用 Docker：Runtime 选 Python 3，Build Command 填 `pip install -r requirements_api.txt`，Start Command 填 `gunicorn -w 1 --threads 8 --timeout 120 -b 0.0.0.0:$PORT furigana_api:app`。

4. 点 Create Web Service，等 3~5 分钟（第一次下词典）。看到日志 `Booting worker` 即成功，页面顶部的 `https://xxx.onrender.com` 就是固定网址。

---

## 方案 C：Hugging Face Spaces（免费，Docker，无信用卡）

1. 注册 https://huggingface.co → 头像 → New Space
2. SDK 选 **Docker**，Visibility 选 Private（只给面试官网址访问），Create
3. 把 `furigana.py`、`furigana_api.py`、`requirements_api.txt`、`Dockerfile.api` 上传到 Space（Files → Upload files，注意 `Dockerfile.api` 要重命名为 `Dockerfile`）
4. 等构建完成，`https://你的用户名-空间名.hf.space` 即可访问

---

## 本地快速验证（不部署也能先测）

```powershell
cd d:\10_Workspace\kanji-tool
.\venv\Scripts\python.exe furigana_api.py
```

另开一个终端：

```powershell
curl.exe -X POST http://localhost:5000/api/furigana -H "Content-Type: application/json" -d '{\"text\":\"六千人が競争する。\"}'
```

（PowerShell 里 `\"` 表示引号；用 Git Bash 或 Postman 会更省事）

---

## 常见问题

- **为什么不直接部署整个学习工具？** 主程序还依赖 SQLite 数据库、后台抓取线程、TTS 等，重且冷启动慢。给面试官测试注音能力，只需要 `furigana.py` 一个文件 + 轻量 API。
- **面试官能测哪些难点？** 直接把下面这些丢进去都能正确注音：多音字（学校に行った / 会議を行った）、熟字训（今日・風邪）、数词（10分・3本・20歳・六千）、字素对齐（競争→きょう+そう、合計→ごう+けい）。
- **返回太详细？** `/api/furigana` 已是简洁三档粒度；想要原始 token 用 `/api/annotate`。
