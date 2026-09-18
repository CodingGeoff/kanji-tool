# 数据库与 Git 协作指南（kanji.db）

> 适用版本：v17+（本文件随 `dbtool.py` 一起引入）
> 目标：**本地数据库的每一次改动，都能安全地提交、推到 GitHub、并在 Render 上直接生效；
> 同时永远不会因为 pull / 合并而丢数据。**

---

## 0. 先看结论（记住这 4 条就够了）

| 结论 | 说明 |
|---|---|
| 根目录 `kanji.db` **必须被 Git 跟踪** | Render 构建时克隆仓库、直接读它当初始数据；忽略它云端就只剩空库 |
| `kanji.db-wal` / `kanji.db-shm` **必须被忽略 + 移出版本控制** | 它们是 SQLite 运行时边车文件，被跟踪后 pull 必然报 “would be overwritten” |
| 数据库相关的操作**只用 `python dbtool.py ...`** | 手写 `git pull` / `git checkout` 很容易丢进度 |
| 提交数据库前**一定要 checkpoint** | WAL 模式下最新写入还在 `-wal` 里，只提交 `kanji.db` 会把旧数据推上云 |

```bash
python dbtool.py status    # 现在什么情况？
python dbtool.py save      # 备份本地库（快照 + 只增不减的并集备份）
python dbtool.py pull      # 安全拉取：先护住数据，再拉远端，再并回本地
python dbtool.py publish   # 提交 + 推送 kanji.db → Render 自动重新部署
python dbtool.py verify    # 校验：完整性 / 孤儿索引 / 是否比备份少数据
python dbtool.py setup     # 一次性配置（换电脑/换克隆时再跑一次）
```

---

## 1. 你当时看到的报错，到底发生了什么

```
Unable to pull when changes are present on your branch.
The following files would be overwritten:
    kanji.db
    kanji.db-shm
    kanji.db-wal
```

这不是 GitHub Desktop 的 bug，而是三个原因叠加：

1. **WAL 边车文件被提交进了仓库。**
   SQLite 打开 WAL 模式后，数据先写进 `kanji.db-wal`（还有共享内存索引 `kanji.db-shm`）。
   这两个文件每次连接数据库都会被改写。它们一旦被 Git 跟踪，
   就成了“永远处于已修改状态”的文件，pull / merge 时 Git 拒绝覆盖 → 上面那段报错。
2. **`kanji.db` 本体也被本地程序改了。**
   学习进度、抓取的语料都写在里面，工作区的 `kanji.db` 与远端版本不同，
   非快进式 pull 需要覆盖它 → 同样被拒绝。
3. **GitHub Desktop 自动 stash。**
   它会把改动塞进 `stash@{0}: !!GitHub_Desktop<main>`。stash 里既有库，
   也有 `textbook.py` 的改动 —— 这些数据当时并没有被真正合并，只是被挪走了。

结果就是：pull 之后云端（仓库）版本盖住了本地版本，
你本地攒的 **452 条语料、10100 行课本计划、153 条历史记录**都不在 `kanji.db` 里了
（它们分别还留在 `_dbbackup/local/`、`_dbbackup/stash/` 和 Git stash 里）。

修复思路：
**让 `kanji.db` 继续被跟踪（Render 要用），只把 WAL 边车请出版本控制，
再用一套“按内容求并集、按进度取更优”的合并把三份库重新拼成最新最全的一份。**

---

## 2. 文件角色分工

| 路径 | 是否提交 | 作用 |
|---|---|---|
| `kanji.db` | ✅ **提交**（唯一数据源） | 本地运行 + Render 初始数据。所有语料/课本/复习进度都在这里 |
| `kanji.db-wal` | ❌ 忽略 | WAL 日志，运行时产生。**绝不提交**（提交它 = 报错 + 二进制冲突） |
| `kanji.db-shm` | ❌ 忽略 | WAL 共享内存索引，同上 |
| `.gitattributes` | ✅ 提交 | 声明 `kanji.db` 是二进制，并挂上 `dbtool.py` 的专用合并驱动 |
| `_dbbackup/` | ❌ 忽略 | 本地备份中心，由 dbtool 管理 |
| `_dbbackup/local/kanji.db` | ❌ 忽略 | **本地权威库**（历次备份的并集，只增不减） |
| `_dbbackup/stash/kanji.db` | ❌ 忽略 | 从 Git stash 里抢救出来的库（一次性归档） |
| `_dbbackup/remote/kanji.db` | ❌ 忽略 | 最近一次从 `HEAD` 导出的仓库版，供合并比对 |
| `_dbbackup/merged/kanji.db` | ❌ 忽略 | 最近一次合并的结果副本 |
| `_dbbackup/snapshots/kanji_*.db` | ❌ 忽略 | 带时间戳的快照（默认保留最近 10 份） |
| `dbtool.py` | ✅ 提交 | 本指南对应的工具 |

`.gitignore` 的正确写法（仓库里已经是这样，**不要**再改回 `*.db`）：

```gitignore
*.db-wal
*.db-shm
*.db-journal
_dbbackup/
.dbtool_merge_*/
# 千万别写 *.db —— 那会让 Render 拿不到 kanji.db
!kanji.db
```

> ⚠️ 为什么不能写 `*.db`：`kanji.db` 是**被跟踪**的文件，写了也不会立刻失效，
> 但只要以后有人 `git rm --cached kanji.db`、或者你换台电脑重新 `git add`，
> 库就会悄悄脱离版本控制，云端从此只有空库。所以这条规则必须明令禁止。
---

## 3. 一次性配置：`python dbtool.py setup`

换电脑、重新克隆仓库、或发现上面那些规则被改动过时，跑一次即可（可重复执行）：

```bash
python dbtool.py setup
```

它会做三件事：

1. 把**已被跟踪**的 `*.db-wal` / `*.db-shm` 从版本控制里移出（磁盘文件保留）；
2. 补齐 `.gitattributes`（`kanji.db -diff -text merge=kanjidb`）；
3. 在本仓库 `.git/config` 里注册合并驱动：
   `merge.kanjidb.driver = "<python路径>" "…/dbtool.py" merge-driver %O %A %B`
   → 以后出现**非快进式合并**时，Git 会自动调用 dbtool 做并集合并，不会再产生二进制冲突。

> 驱动用的是你运行 `setup` 时的那个 Python（用 venv 里的 python 跑，就记 venv 路径）。
> 换了 Python 或移动了项目目录，重新跑一次 `setup` 即可。

---

## 4. 四件日常事

### 4.1 本地学完，想把数据同步到 Render ⭐ 最常用

```bash
# 1) 先关掉正在运行的服务（start.bat 窗口 / Ctrl+C），否则数据库被占用
# 2) 一条命令搞定：checkpoint → 提交 kanji.db → 推送
python dbtool.py publish -m "更新数据库"
```

- 只提交 `kanji.db` 这一个文件，不会顺手带走你其它没写完的改动；
- 推送成功后 Render 检测到 push，**自动重新部署**，1~3 分钟后新数据生效
  （部署日志出现 `Booting worker` 即完成，刷新网页就能看到）；
- 想先看会发生什么：`python dbtool.py publish --dry-run`；
- 只想本地提交不上线：`python dbtool.py publish --no-push`。

### 4.2 要拉取远端更新（别在 GitHub Desktop 里直接 Pull）

```bash
python dbtool.py pull
```

按顺序做四步，任何一步都不会丢数据：

1. `save`：当前库做快照，并把数据并进 `_dbbackup/local/kanji.db`（只增不减）；
2. 工作区的 `kanji.db` 若与 `HEAD` 不同 → 先回退（数据已在上面那份备份里）；
3. `git pull`（若是合并，`kanji.db` 由 dbtool 的合并驱动自动处理）；
4. 把本地那份并回新的仓库版 → 写进 `kanji.db`，并打印补进来多少行。

拉完如果提示“本地库带着本地数据”，说明合并成功，想上线就接着跑 `publish`。

### 4.3 备份 / 存档

```bash
python dbtool.py save            # 快照 + 更新 _dbbackup/local（并集，不会丢）
python dbtool.py save --keep 20  # 快照保留最近 20 份
```

### 4.4 体检

```bash
python dbtool.py status   # 文件/WAL 状态、各表行数、与备份差异、Git 状态、被跟踪的边车文件
python dbtool.py verify   # integrity_check、孤儿索引、重复/空句子、是否比备份少数据
```

`status` 里这两行是健康标志：

```
被跟踪的边车文件   无（正确，pull 不会再报 would be overwritten）
kanji.db          与 HEAD 一致 / 与 HEAD 有差异（有未提交的进度）
```

---

## 5. 合并规则：为什么合了不会乱、不会丢

`merge_db()` 以**主库**（默认 `_dbbackup/local/kanji.db`，没有就用当前 `kanji.db`）为准，
把仓库版 `HEAD:kanji.db`（以及 `--from` 指定的副本）**只补缺、不覆盖**地并进来：

| 表 | 合并规则 |
|---|---|
| `sentences` | 按**文本**取并集。能沿用原 id 就沿用；id 撞车就分配新 id，并记录 `旧id→新id` 映射 |
| `kanji_index` / `book_sentences` / `fav_sentences` | 先按映射改写 `sentence_id`，再校验“映射后两条句子的文本完全一致”；对不上就**整行放弃**（宁可不合，绝不指向错误句子） |
| `srs` / `book_progress` | 进度取更优：`stage` 高者胜，同阶段看 `last_at`，再看总作答数 —— 复习进度**只前进不倒退** |
| `book_plan`（学习计划） | 补进缺失的日程行；`done` 打勾状态用 OR 合并（勾过的不变回未勾） |
| `history` | 按 `(ts, type, detail)` 去重，同一条事件只留一份 |
| `settings` | 同名以本库为准；本库为空值时用源库补（云端写过的 v17 学习者模型能带回来） |
| `songs` / `books` / `book_lessons` / 其它 | 按自然唯一键（没有唯一键就用行 id）补缺，避免同一首歌/同一本书被复制成两份 |
| 主库没有的表 | 按源库 DDL 自动建表再补数据（将来版本新增表也不会丢） |

两张额外保险：

- **黑名单（不复活脏数据）**：dbtool 会读 `git` 历史里最近几个提交的 `kanji.db`，
  找出“老版本有、最新版本没有”的句子文本 —— 那是上游**刻意清理**掉的脏语料，
  合并时不会从旧副本里把它们复活（默认回看 2 个提交，`--depth N` 可调）。
- **`--purge-deleted`**：如果主库自己还残留这些脏句子，加上这个参数会连它的
  `kanji_index` / 收藏 / 课本引用一起删掉。

```bash
# 一次性抢救（本次故障复盘用的就是这个）：把归档的 stash 库也并进来
python dbtool.py merge --from _dbbackup/stash/kanji.db \
                       --exclude books,book_lessons --purge-deleted
```

> `--exclude` 用来排除某个副本里的**过期用户数据**（例：stash 里还留着当年删掉的“测试书”，
> 不排除会被当成新书复活）。内容类表（句子、索引、历史）不需要排除。

---

## 6. Render 上的行为（务必理解这一点）

Render 免费套餐的**磁盘是临时的**：每次重新部署 / 实例重启，工作目录都会回到
Git 仓库里的那一份 `kanji.db`。由此得到两条铁律：

| 方向 | 怎么做 |
|---|---|
| **本地 → 云端**（把本地语料/进度/课本送上云） | `python dbtool.py publish` → 把 `kanji.db` 提交推送 → Render 自动重部署 → 网页直接读到新库 |
| **云端 → 本地**（把云上新增的数据带回来） | 网页「统计·历史」页的 **📥 导出备份 / 💾 备份数据库** 下载下来，本地再导进去；或者截图记录、下次 `publish` 覆盖回去 |

部署侧的链路（仓库里现成，无需改动）：

```
GitHub push → Render 拉取仓库 → pip install -r requirements.txt → gunicorn app:app
                                        ↑
                          kanji.db 与代码一起被拉下来（因为它在版本库里）
                          app.py / db.py 的 DB_PATH 就是仓库根目录的 kanji.db
```

验证部署是否吃到新数据：

1. Render 控制台 → 你的服务 → **Logs**，看到新的部署流水线跑完、出现 `Booting worker`；
2. 打开网址 → 「关于」里的 BUILD 哈希/时间应与刚才的 commit 一致；
3. 「统计·历史」页看语料总数，应该等于本地 `python dbtool.py status` 里看到的 `sentences` 数量。

> 如果你希望云端数据**永久保留**（不随部署回滚），需要 Render 的持久磁盘（付费），
> 或者继续用上面的“导出备份 → 本地 → publish”人工归档法。

---

## 7. 常见问题（FAQ）

**Q1：pull 又报 `The following files would be overwritten` 怎么办？**
先用 `python dbtool.py setup` 看一眼“被跟踪的边车文件”是否为空；
再有本地改动时不要手写 `git pull`，直接 `python dbtool.py pull`。

**Q2：提交了 kanji.db，为什么 Render 上还是旧数据？**
① 检查是否真的推送成功（`git status` 是否 `ahead`）；② `publish` 前是否关了本地服务
（没关的话 checkpoint 不完整，提交的是旧快照）；③ 部署是否还在跑（看 Logs）。

**Q3：`数据库被占用` / `database table is locked` ？**
本地服务还开着。关掉 `start.bat` 窗口或结束占用 `kanji.db` 的 python/gunicorn 进程再执行。

**Q4：我在 Render 网页上点了一堆收藏/学了一堆字，怎么带回本地？**
云端磁盘不持久，先导出：网页「📥 导出备份」下载 JSON，本地「📥 导入备份」合并进去，
然后再 `python dbtool.py publish` 把合并后的库推回云端。

**Q5：`_dbbackup/` 会占很多磁盘吗？**
每份约 25MB；`snapshots/` 默认只留最近 10 份（`save --keep N` 可调）。
整个目录不进版本库，删了也不影响仓库，但它是你丢数据时的最后一道保险。

**Q6：Git stash 里还有一份旧库，要不要 pop？**
**不要 pop**，它会用旧数据覆盖现在的 `kanji.db`（旧库里没有这 10100 行课本计划）。
它的数据已经在本次合并里被完整吸收（见第 8 节）。确认页面一切正常后，
可以放心 `git stash drop`（数据在 `_dbbackup/stash/` 还有一份归档）。

**Q7：`kanji.db` 25MB 每次提交都进历史，仓库会不会爆？**
单文件远低于 GitHub 100MB 上限，正常用没问题；但如果一年推几百次，
仓库体积会线性增长。省心做法：平时多 `save` + 少 `publish`，
只在“确实想同步到云端”时 `publish`（每次 publish 只增加一份库的历史）。

**Q8：能换成 Git LFS 吗？**
可以，但 Render 侧需要 LFS 支持、本地也要额外配置，收益不大，本项目不采用。

---

## 8. 本次故障复盘（2026-09-18）

三个阶段、三份库，各自都攒了不同的数据：

| 库 | 句子 | kanji_index | history | book_plan | 说明 |
|---|---|---|---|---|---|
| 仓库版（`HEAD`，已被清理） | 11981 | 56872 | 4 | 0 | pull 后占据工作区的那份 |
| `_dbbackup/local`（本地学习库） | 12433 | 59084 | 157 | 10100 | 你平时学习用的那份 |
| `_dbbackup/stash`（从 Git stash 抢救） | 12847 | 59885 | 184 | 0 | GitHub Desktop 自动 stash 那份 |

抢救动作（已执行）：

```bash
python dbtool.py setup
python dbtool.py save                       # 快照 + local 备份取并集
python dbtool.py merge --from _dbbackup/stash/kanji.db \
                       --exclude books,book_lessons --purge-deleted
python dbtool.py verify                     # 完整性 + 无孤儿索引 + 不比备份少
```

合并结果（现在的 `kanji.db`）：

| 表 | 合并前（仓库版） | 合并后 |
|---|---|---|
| sentences | 11981 | **13564** |
| kanji_index | 56872 | **69494** |
| history | 4 | **233** |
| book_plan | 0 | **10100** |
| settings | 3 | 3（含云端的 `edu_learner_model` / `edu_sessions`） |
| songs / books / book_lessons / book_kanji / book_words / book_sentences | 41 / 1 / 9 / 572 / 707 / 214 | 不变（一条不丢） |

另外：`stash` 里那份 `textbook.py` 改动已过时（当前代码已用 `new_kanji` / `new_words`
的方式实现，`cloze_round_chars` 全仓库无引用），因此只吸收了库数据、没有回放代码改动。
仓库里同时清理掉了两个临时脚本（`_dbstats.py`、`_dbmerge.py`），
它们的功能已由 `dbtool.py`（带测试）取代。

---

## 9. 速查表

| 我想…… | 命令 |
|---|---|
| 看现在的状态 | `python dbtool.py status` |
| 备份本地库 | `python dbtool.py save` |
| 合并出“最新最全”的库 | `python dbtool.py merge` |
| 安全拉取远端更新 | `python dbtool.py pull` |
| 把数据同步到 Render | `python dbtool.py publish -m "更新数据库"` |
| 校验库是否健康 | `python dbtool.py verify` |
| 换电脑后的配置 | `python dbtool.py setup` |
| 跑回归测试 | `python test_dbtool.py` |
| 关掉本地服务 | 关闭 `start.bat` 窗口，或 `Ctrl+C` |

