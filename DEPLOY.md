# 部署指南（一步一步照做即可）

## ⚠️ 先说清楚：为什么不能用 Netlify / Firebase

| 平台 | 结论 | 原因 |
|---|---|---|
| Netlify | ❌ 不行 | 只能托管静态网页和 JS 函数。本项目是 **Python 后端**（Flask + MeCab/Sudachi 形态素词典 + SQLite + 后台抓取线程），Netlify 跑不了 |
| Firebase Hosting | ❌ 不行 | 同样只托管静态文件 |
| Firebase Cloud Functions | ⚠️ 理论可行但强烈不推荐 | 函数是"请求来了才启动"的短命进程：后台持续抓取线程无法常驻、SQLite 无处持久化、MeCab+Sudachi 词典 300MB+ 让冷启动极慢，还可能超包体限制 |

本项目需要的是一台**能常驻运行 Python 的服务器**。下面给你三个免费方案，**推荐方案 A（Render）**，从 GitHub 仓库直连、全程点鼠标。

---

## 方案 A：Render（推荐 ⭐ 免费、直连 GitHub、最简单）

### 第 1 步：把代码推到你的 GitHub 仓库

在本项目目录打开终端（确保包含 `app.py`、`requirements.txt`、`render.yaml` 这些文件）：

```bash
git init                      # 若仓库已初始化则跳过
git remote add origin https://github.com/<你的用户名>/<你的仓库名>.git
                              # 若已添加过 remote 则跳过
git add .
git commit -m "日语汉字学习工具"
git branch -M main
git push -u origin main
```

> ⚠️ **`kanji.db` 必须一起推上去，而且不要把它加进 `.gitignore`**。
> Render 构建时克隆仓库、直接读这个文件当初始数据（语料 / 课本 / 复习进度）。
> 一旦它脱离版本控制，云端就只剩空库——详见 [`DATABASE.md`](DATABASE.md)。
> 数据库相关的日常操作请统一使用 `python dbtool.py ...`（备份 / 合并 / 安全拉取 / 发布）。

### 第 2 步：注册并创建服务

1. 打开 https://render.com ，点 **Get Started**，选 **Sign in with GitHub** 直接用 GitHub 账号登录
2. 登录后点右上角 **New +** → **Web Service**
3. 在列表里找到你的仓库，点 **Connect**（第一次会提示授权 Render 访问 GitHub，点允许）

### 第 3 步：填配置（大部分自动识别）

| 配置项 | 填什么 |
|---|---|
| Name | 随便，如 `kanji-tool` |
| Region | `Singapore`（离你最近） |
| Branch | `main` |
| Runtime | `Python 3` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn -w 1 --threads 8 --timeout 120 -b 0.0.0.0:$PORT app:app` |
| Instance Type | **Free** |

> 因为仓库里有 `render.yaml`，多数配置会自动填好，核对一遍即可。

### 第 4 步：点 Deploy

点 **Create Web Service**，等 5～10 分钟（第一次要下载形态素词典，较慢）。看到日志出现 `Booting worker` 即成功。页面顶部的 `https://kanji-tool-xxxx.onrender.com` 就是你的专属网址，手机电脑都能访问。

### 之后怎么更新

**改代码**：本地改完代码，`git add . && git commit -m "更新" && git push` —— Render 检测到推送会**自动重新部署**。

**改数据（数据库）**：不要手写 git 命令，用 `dbtool.py` 一条命令完成
「checkpoint → 只提交 kanji.db → 推送」：

```bash
# 先关掉本地正在运行的服务（start.bat 窗口 / Ctrl+C），否则数据库被占用
python dbtool.py publish -m "更新数据库"
```

推送后 Render 自动重新部署，1~3 分钟后新数据生效（Logs 出现 `Booting worker`）。
拉取远端更新时也用托管命令，避免 pull 覆盖本地数据库：

```bash
python dbtool.py pull     # 备份 → 清理本地库改动 → pull → 把本地数据并回新仓库版
```

> 完整原理、合并规则、FAQ 见 [`DATABASE.md`](DATABASE.md)。

### Free 套餐的两个限制（重要）

1. **15 分钟无访问会休眠**，下次打开要等约 1 分钟冷启动——个人学习工具完全够用
2. **磁盘不持久**：重新部署/重启后，云端新增的数据会回到仓库里 `kanji.db` 的状态。对策：
   - 语料会被后台线程自动重新抓取，损失不大
   - 学习进度定期备份：打开 `语料库 → 💾备份数据库` 下载 `kanji_backup.db`；想推回仓库请用 `python dbtool.py publish`
     （它提交前会做 checkpoint，保证把 WAL 里的最新数据一起写进 kanji.db）
   - 想**长期保留**：网页「📥 导出备份」下载 JSON（或「💾 备份数据库」下载 `kanji_backup.db`），
     在本地「📥 导入备份」合并进本地库，再 `python dbtool.py publish -m "更新数据库"` 推回云端；
     这样「云端 → 本地 → 仓库 → 云端」就形成了闭环存档
   - 记住：**云端磁盘算草稿纸，仓库里的 `kanji.db` 才是正式存档**（详见 `DATABASE.md`）
   - 或升级 Render 付费盘（$7/月起）实现真持久化

---

## 方案 B：Hugging Face Spaces（免费、用 Docker、无休眠时间更长）

1. 注册 https://huggingface.co ，点头像 → **New Space**
2. Space name 随意；License 随意；SDK 选 **Docker**；Visibility 建议 Private；点 **Create Space**
3. 把本项目文件推到 Space 仓库（仓库里已有现成的 `Dockerfile`，无需改动）：
   ```bash
   git remote add hf https://huggingface.co/spaces/<你的用户名>/<space名>
   git push hf main
   ```
   （或者直接在 Space 网页上 Files → Upload files 拖拽上传所有文件）
4. 等待自动构建完成，页面即是你的应用

> HF Spaces 免费版同样是临时磁盘，备份方法同上。

---

## 方案 C：Fly.io / Railway（也支持，配置类似）

仓库里的 `Dockerfile` 直接可用：`fly launch` 或在 Railway 里 New Project → Deploy from GitHub repo，一路默认即可。Railway 每月有 $5 免费额度；Fly.io 免费额度可挂一个小实例并支持**免费持久卷**（3GB），如果你在意数据持久化，Fly.io 是免费方案里最完整的，但命令行操作稍多。

---

## 本地运行（随时可用的兜底）

```bash
pip install -r requirements.txt
python3 app.py            # 打开 http://localhost:5000
```

数据全在本地 `kanji.db`，永远不会丢。

## 常见问题

- **部署后 TTS 朗读没声音？** edge-tts 需要访问微软服务器，Render/HF 网络均可正常访问；若失败，前端会自动退回浏览器本地语音
- **首次部署很慢？** unidic-lite + sudachidict 词典约 300MB，只有第一次构建慢
- **想要自定义域名？** Render 免费版支持：Settings → Custom Domain
