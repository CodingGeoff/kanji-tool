# -*- coding: utf-8 -*-
"""
性能与内存预算工具（v26 性能重构）
================================================================
背景：Render 免费实例只有 512MB 内存、不足 1 核的 CPU 配额。
此前启动时三路后台预热（RAG 联邦索引 / 结构相似索引 / 听写联想键）
要在内存里同时持有 5 份重复数据（词元列表、词元集合、bigram 集合、
bigram 倒排、归一化文本），2.4 万句语料就吃掉 ~1.4GB RSS，
云端直接 OOM 重启，重启又预热、预热又 OOM，形成死循环——
这就是「云端特别容易超内存」「打开页面所有功能卡半天」的根因。

本模块提供统一的内存预算查询：
- `available_mb()`：容器（cgroup v2/v1）或物理机的可用内存；
- `index_budget_mb()`：允许给内存索引花的预算（默认可用内存的 1/4，
  并被 KANJI_INDEX_BUDGET_MB 环境变量覆盖）；
- `doc_cap(default, env)`：把预算换算成「最多索引多少篇文档」，
  供各索引在建库前自检，语料再大也按最新 N 篇降级，绝不吃爆内存；
- `warmup_allowed()`：启动预热总开关（KANJI_WARMUP=off|on|auto）。

所有函数都绝不抛异常——性能护栏本身不能把业务打挂。
"""
import os

try:
    import threading
except Exception:                                     # pragma: no cover
    threading = None


def _read_int(path):
    try:
        with open(path) as f:
            return int(f.read().strip())
    except Exception:
        return None


def _cgroup_available_mb():
    """cgroup v2 → memory.max/memory.current；v1 → memory.limit_in_bytes/usage_in_bytes。"""
    # cgroup v2（Render / HF Spaces / 现代容器）
    limit = _read_int('/sys/fs/cgroup/memory.max')        # -1（或 huge）= 无限制
    if limit is not None and 0 < limit < (1 << 50):
        cur = _read_int('/sys/fs/cgroup/memory.current') or 0
        return max(0, (limit - cur) / 1048576.0)
    # cgroup v1
    limit = _read_int('/sys/fs/cgroup/memory/memory.limit_in_bytes')
    if limit is not None and 0 < limit < (1 << 50):
        cur = _read_int('/sys/fs/cgroup/memory/memory.usage_in_bytes') or 0
        return max(0, (limit - cur) / 1048576.0)
    return None


def _meminfo_available_mb():
    with open('/proc/meminfo') as f:
        for line in f:
            if line.startswith('MemAvailable:'):
                return int(line.split()[1]) / 1024.0
    return None


_CACHE = {'t': 0.0, 'mb': None}
_CACHE_TTL = 15.0          # 秒：内存余量变化很快，但不值得每次都开文件


def available_mb():
    """当前可用内存（MB，float）。读不到就返回 512（保守假设小容器）。"""
    import time
    now = time.time()
    if _CACHE['mb'] is None or now - _CACHE['t'] > _CACHE_TTL:
        mb = _cgroup_available_mb()
        if mb is None:
            mb = _meminfo_available_mb()
        if mb is None:
            mb = 512.0
        _CACHE['mb'] = mb
        _CACHE['t'] = now
    return _CACHE['mb']


def index_budget_mb():
    """内存索引总预算（MB）。环境变量 KANJI_INDEX_BUDGET_MB 可覆盖。

    供 RAG 联邦索引 / 结构相似索引 / 听写联想键分摊；默认可用内存的
    1/4（本地大内存机器上限 768MB，避免毫无必要的巨型索引拖慢构建），
    小容器下限 96MB（保证小语料功能完整可用）。
    """
    env = os.environ.get('KANJI_INDEX_BUDGET_MB')
    if env:
        try:
            return max(32.0, float(env))
        except ValueError:
            pass
    mb = available_mb()
    budget = mb / 4.0
    return min(max(budget, 96.0), 768.0)


# 每篇文档（一个句子）在紧凑索引里的实测内存开销（MB / 万篇，tracemalloc 实测）：
#   RAG 联邦索引 ~22MB/万篇（含词元倒排 + bigram 倒排 + payload）
#   结构相似索引 ~5MB/万篇、听写联想键 ~7MB/万篇、译文倒排 ~3MB/万篇。
# 取 30MB/万篇（约 1.4 倍余量，覆盖堆碎片与调用方叠加）做统一换算；
# 各索引另有自己的默认硬上限，两者取小。
_MB_PER_10K_DOCS = 30.0


def doc_cap(default, env=None):
    """把 index_budget_mb() 换算成「最多索引多少篇文档」。

    - default：各索引自己的默认上限（没有预算信息时的兜底值）；
    - env：专属环境变量名（如 KANJI_RAG_MAX_DOCS），优先级最高；
    - 返回值恒 > 0：预算再小也至少索引 5000 篇（小语料功能必须完整）。
    """
    if env:
        v = os.environ.get(env)
        if v:
            try:
                return max(1000, int(float(v)))
            except ValueError:
                pass
    try:
        budget_docs = int(index_budget_mb() * 10000.0 / _MB_PER_10K_DOCS)
    except Exception:
        budget_docs = default
    return max(5000, min(default, budget_docs))


_TRIM = None


def trim_memory():
    """把 glibc 堆里的空闲块归还系统（malloc_trim(0)）。

    大索引构建期间 array/dict 的增量扩容会在 C 堆里留下空洞；构建完成后
    调一次 trim 能立刻归还一部分（实测几 MB～几十 MB，平台相关）。
    不可用时静默跳过——这只是锦上添花，不影响正确性。"""
    global _TRIM
    try:
        if _TRIM is None:
            import ctypes
            libc = ctypes.CDLL('libc.so.6', use_errno=False)
            libc.malloc_trim.argtypes = [ctypes.c_size_t]
            libc.malloc_trim.restype = ctypes.c_int
            _TRIM = libc.malloc_trim
        _TRIM(0)
    except Exception:
        _TRIM = False


def warmup_allowed():
    """启动预热开关。KANJI_WARMUP=off 关闭 / on 强制开启 / auto（默认）看内存。

    auto：可用内存 ≥ 220MB 才预热。紧凑重写后 RAG 索引对 2 万句语料
    只要几十 MB，正常实例都过得了这道闸；真正的小内存容器自动跳过，
    索引改为首个请求时惰性构建，宁可让第一个用户多等几秒也不再 OOM。
    """
    mode = (os.environ.get('KANJI_WARMUP') or 'auto').strip().lower()
    if mode in ('0', 'off', 'no', 'false'):
        return False
    if mode in ('1', 'on', 'yes', 'true'):
        return True
    try:
        return available_mb() >= 220.0
    except Exception:
        return False


def paced(steps):
    """顺序执行 [(name, fn), ...] 的预热任务，一步一歇，绝不并发抢 CPU。

    旧实现三路预热线程同时开跑，在单核容器上等于三个 CPU 密集任务
    抢一个核，页面打开的每个请求都在排队——「点什么卡什么」。
    现在统一由一个线程串行执行，每步之间让出 CPU。
    """
    if not threading:
        for _name, fn in steps:
            try:
                fn()
            except Exception:
                pass
        return

    def _run():
        for name, fn in steps:
            try:
                fn()
            except Exception as e:
                try:
                    print('[perf] 预热步骤 %s 失败（不影响启动）：%s' % (name, e))
                except Exception:
                    pass

    t = threading.Thread(target=_run, daemon=True, name='perf-warmup')
    t.start()
    return t
