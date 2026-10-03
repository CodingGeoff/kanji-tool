# 性能架构（v26 重构：内存与出题速度）

> 目标环境：本地多核机器（语料几万句，内存管够）与云端免费实例
> （Render free：512MB 内存、不足 1 核 CPU 配额）必须**同一套代码**都跑得动。

## v26 之前的问题（用户可感知的症状）

| 症状 | 根因 |
| --- | --- |
| 云端（Render）特别容易超内存 | 启动即三路预热：RAG 联邦索引（每篇文档存 5 份数据：词元列表、词元集合、bigram 集合、bigram 倒排、归一化文本）+ 结构相似索引（逐句 dict 签名）+ 听写联想键（42.6 万个 (字符串, int) tuple）。2.4 万句语料合计 ~1.4GB RSS，512MB 实例直接 OOM → 重启 → 再预热 → 再 OOM 死循环 |
| 打开页面除了 KTV 歌词全部卡半天 | 三个 CPU 密集预热线程启动即全速并发开跑，单核容器上所有 HTTP 请求排队；KTV 页只读 songs 表所以独快 |
| 听力练习几乎加载不出来 | `make_quiz` 每卷把 2 万行译文拉进内存重建倒排索引（~1.2s + 几十 MB 临时对象）、听音选汉字对 6 万词条全库扫 + 逐条 difflib（~1.4s）、听后选义对每个候选跑 SequenceMatcher（每卷 4.5 万次 ~0.8s）——再叠加 CPU 被预热抢走、进程随时 OOM 重启 |
| 语料越大越卡 | 上述所有成本都随句数**线性甚至超线性**增长，且 ORDER BY RANDOM 全表扫描、结构检索全库逐句 LCS（万句 ~3 秒）|

## v26 的算法与结构

### 1. 内存：紧凑倒排 + 查询侧累计（rag.py / structsim.py / listening.py）

核心思想：**索引里只存「词 → 文档号」的机器码倒排（`array('l')`），绝不
为每篇文档常驻集合对象**。所有需要「文档的词集合/bigram 集合」的计算，都
改成对**查询侧**的少量词元/bigram 各扫一遍倒排表，把命中数累计到文档上：

- 覆盖度 `|q ∩ doc|` = 查询词元倒排扫描时的命中计数（BM25 打分顺带产出，零额外成本）；
- Dice `2·|Q∩D|/(|Q|+|D|)` = 查询 bigram 倒排扫描的命中计数 + 每文档 bigram 数（一个 int 数组）。

数学上与旧的逐文档集合交**完全等价**（查询词元/bigram 去重后倒排表内文档号不重复），
实测等价性有对拍测试保证（test_search / test_rag_multi / test_listening 全过）。

内存对比（2.4 万句语料，tracemalloc 实测驻留）：

| 索引 | 旧 | 新 |
| --- | --- | --- |
| RAG 联邦索引（三通道 BM25 + Dice） | ~400MB | **~52MB** |
| 结构相似索引（全库签名） | ~255MB | **~11MB** |
| 听写联想键（42.8 万前缀） | ~124MB（RSS 峰值 ~450MB） | **~20MB**（串接 blob + 两个偏移数组） |

另外：sqlite 读取一律流式游标（不再整库 `fetchall`），语料超过内存预算时
按最新 N 篇降级（`meta.index.capped` 如实标注），**语料再大也不会吃爆内存**。

> 关于 RSS 的一个重要事实：进程 RSS 里 ~400-500MB 是 unidic/sudachi 词典的
> **mmap 文件页（shared clean）**，内存压力下内核会自动回收再按需读回，不会
> 导致 OOM；真正导致 OOM 的是**匿名内存**，v26 后全功能工作集的匿名内存
> ≈ 150MB（旧版仅三路索引就 >700MB），512MB 实例余量充足。

### 2. 启动：单线程串行预热 + 内存闸门（perf.py + app.py/rag.py）

- 只有 RAG 联邦索引、RagIndex、听力两份全局索引会预热，**单线程串行、一步一歇**，
  不再三路并发抢 CPU；
- 结构相似索引改为**首个整句检索时惰性构建**（紧凑版万句 ~1.5 秒）；
- 听写联想索引随「输入联想」功能默认关闭，**绝不自动预热**（见下）；
- `perf.warmup_allowed()`：`KANJI_WARMUP=off` 或可用内存 < 220MB 时完全跳过预热，
  全部惰性构建（宁可第一个用户多等几秒也不 OOM）；
- `perf.doc_cap()`：按 `perf.index_budget_mb()`（可用内存 1/4，`KANJI_INDEX_BUDGET_MB`
  可覆盖）把各索引的文档量上限统一换算，语料超过上限只索引最新 N 篇。

### 3. 听力出题（listening.py）

| 热点 | 旧算法 | 新算法 |
| --- | --- | --- |
| 听后选义 | 每卷拉 2 万行译文重建倒排；对每个候选跑 difflib（每卷 4.5 万次） | 全局紧凑倒排（跨卷共享、签名换代）；倒排单遍**精确**累计共享 IDF 权重，只对 top-48 跑 difflib（~150 次） |
| 听音选汉字 | 每题全库扫 6 万词条 × 2 次 SequenceMatcher | 三张倒排（共享汉字 / 同读音 / 读音 bigram）并集取候选（几十~几百个）再精算 |
| 题源随机抽样 | `ORDER BY RANDOM()` 全表扫描+排序 | id 密集时随机 id 直抽（O(need·log n)，分布等价）；稀疏时自动退回旧路径 |
| 整句听写联想键 | 3 万句逐句重跑形态素引擎（~70 秒 CPU） | 复用入库 `sentences.tokens`（秒级）；判卷/出题仍用现场注音保证读音与当前引擎一致 |
| 辨句干扰池 | `lru_cache(maxsize=1)` 永不失效（语料变了还是旧池） | (count, max_id) 签名缓存，语料一变自动重抽 |

实测：10 题一卷从 **~4.1s → 0.1~0.2s**（热），首卷 ~1.3s（含一次性建索引）。

### 4. 结构相似检索（structsim.py）

两阶段算法替换全库逐句 LCS：综合分 = 0.45×助词 + 0.25×LCS + 0.15×句尾 + 0.15×长度，
其中 LCS ∈ [0,1]，故 `cheap = 0.45×助词 + 0.15×句尾 + 0.15×长度` 是严格下界。
第一阶段对全库只算 cheap（纯算术）；第二阶段只对 `cheap+0.25 ≥ 入选线` 的候选
算 LCS（早停安全：候选按 cheap 降序）。与旧算法对拍 12 组查询：11 组完全一致，
1 组仅同分并列内部顺序不同。万句语料 **~3.4s → ~40ms**。

签名紧凑化：助词/词性/句尾全部驻留成小整数（驻留表 + int 元组），相似度用
整数集合/权重运算；并集权重用「查询侧总权重 + 文档侧总权重 − 交集权重」恒等式
还原，不再逐句建集合。

### 5. 数据库（db.py）

- `idx_sentences_source`：按题源（如 `source='passage'`）随机抽样与
  `GROUP BY source` 统计不再全表扫；
- `idx_history_type_ts`：`/api/stats` 的「今天复习多少个」不再扫全历史表；
- 均为幂等 `CREATE INDEX IF NOT EXISTS`，对多设备同步的旧库安全。

### 6. 整句听写「输入自动联想」（默认关闭，口令开启）

v26 起默认关闭（`listening.DEFAULT_CFG.suggest_enabled=False`，存量用户同样生效）：

- 服务端：`POST /api/listening/suggest-secret`（口令 `SUGGEST_SECRET`）是唯一开关；
  普通 `POST /api/listening/cfg` 改不动它；关闭时立即释放全部索引内存；
- 前端：配置面板不出现该选项；开启入口藏在「关于」对话框——4 秒内连点
  「服务器版本」一行 5 次 → 输入口令；
- 开启后索引才会在后台构建（复用入库 tokens，秒级）；构建期间联想请求返回空，
  不打断手打。

## 环境变量一览

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `KANJI_WARMUP` | `auto` | `off` 关闭全部启动预热；`on` 强制；`auto` 看内存（≥220MB 才预热） |
| `KANJI_INDEX_BUDGET_MB` | 可用内存 1/4（96~768MB） | 内存索引总预算 |
| `KANJI_RAG_MAX_DOCS` / `KANJI_STRUCT_MAX_DOCS` / `KANJI_SUGGEST_MAX_DOCS` / `KANJI_TRANS_INDEX_MAX_DOCS` | 200000 / 200000 / 30000 / 20000 | 各索引文档量硬上限（与预算换算值取小） |
| `KANJI_SEED_PASSAGES` | `1` | 既有变量：内置篇章补种开关 |

## 回归测试

```bash
python3 test_listening.py            # 听力全链路（含新算法下的题型/判卷等价性）
python3 test_listening_dictation.py  # 听写/联想（含默认关闭 + 口令开关）
python3 test_search.py               # 检索/省流
python3 test_rag_multi.py            # RAG 高级特性（歌名置顶/来源优先级/缓存）
python3 test_lyric_search.py         # 歌词检索
python3 test_api.py <port>           # HTTP 全链路（需先 python3 app.py）
python3 test_builder.py test_cloze.py test_ktv.py   # 组句/挖空/KTV
```
