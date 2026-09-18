# -*- coding: utf-8 -*-
"""AI 翻译模块（v18）：缺译例句的 AI 补译 + 翻译来源标记。

设计要点
--------
1. 多 Provider：spark（讯飞星火，默认）/ deepseek / openai（OpenAI 兼容接口）/ mock。
   三个在线 Provider 统一走 `/chat/completions` 协议；星火用 MaaS v2 地址
   （https://maas-api.cn-huabei-1.xf-yun.com/v2），请求体按星火文档微调：
   max_completion_tokens 代替已废弃的 max_tokens，且不传 temperature/top_p。
2. 无静默降级：在线 Provider 出错（断网、无 key、4xx/5xx、超时）时，
   直接返回 error，绝不悄悄换成 mock 结果欺骗用户（诚实性红线）。
3. 自动清洗：sanitize() 去掉模型常带的 ```围栏、"翻译："前缀、首尾引号；
   清洗后为空则视为失败，不写入空翻译。
4. 来源标记：成功写入的译文一律打 translation_source='ai:<provider>:<model>'，
   人工/导入译文为 ''（空字符串），前端可按"缺翻译"筛选。
5. 失败跳过：批量补译遇到单条失败只记 failed 并继续，不中断、不覆盖原文。

配置持久化：db.settings 表（key='ai_translate_config'，JSON）。
"""
import json
import re
import time

PROVIDERS = ('deepseek', 'spark', 'openai', 'mock')

AI_TRANSLATE_VERSION = 'v18'

DEFAULT_MODELS = {
    'deepseek': 'deepseek-chat',
    'spark': 'spark-x2.5-4b',
    'openai': 'gpt-4o-mini',
    'mock': 'mock-v1',
}

DEFAULT_BASE_URLS = {
    'deepseek': 'https://api.deepseek.com/v1',
    'spark': 'https://maas-api.cn-huabei-1.xf-yun.com/v2',
    'openai': 'https://api.openai.com/v1',
    'mock': '',
}

# 默认服务商：讯飞星火（用户指定；DeepSeek 仅作翻译质量再三被投诉时的备选）
DEFAULT_PROVIDER = 'spark'

DEFAULT_PROMPTS = {
    'zh': ('你是一名资深日中翻译。请把用户给出的日语句子翻译成简体中文。'
           '只输出译文正文，不要解释、不要注音、不要加引号或代码块。'),
    'en': ('You are a professional Japanese-English translator. '
           'Translate the given Japanese sentence into natural English. '
           'Output ONLY the translation, no explanations, no quotes, no code fences.'),
}

CONFIG_KEY = 'ai_translate_config'


class AIConfig:
    """AI 翻译配置（可 JSON 序列化）。"""

    def __init__(self, provider='spark', model='', api_key='', base_url='',
                 lang='zh', max_tokens=500, temperature=0.3, timeout=30):
        self.provider = provider if provider in PROVIDERS else DEFAULT_PROVIDER
        self.model = model or DEFAULT_MODELS[self.provider]
        self.api_key = api_key or ''
        self.base_url = (base_url or DEFAULT_BASE_URLS.get(self.provider, '')).rstrip('/')
        self.lang = lang if lang in ('zh', 'en') else 'zh'
        try:
            self.max_tokens = max(1, min(int(max_tokens), 4000))
        except (TypeError, ValueError):
            self.max_tokens = 500
        try:
            self.temperature = max(0.0, min(float(temperature), 2.0))
        except (TypeError, ValueError):
            self.temperature = 0.3
        try:
            self.timeout = max(5, min(int(timeout), 300))
        except (TypeError, ValueError):
            self.timeout = 30

    @classmethod
    def from_dict(cls, d):
        d = d or {}
        return cls(provider=d.get('provider', DEFAULT_PROVIDER),
                   model=d.get('model', ''),
                   api_key=d.get('api_key', ''),
                   base_url=d.get('base_url', ''),
                   lang=d.get('lang', 'zh'),
                   max_tokens=d.get('max_tokens', 500),
                   temperature=d.get('temperature', 0.3),
                   timeout=d.get('timeout', 30))

    def to_dict(self, hide_key=True):
        return {'provider': self.provider,
                'model': self.model,
                'api_key': ('***' if self.api_key else '') if hide_key else self.api_key,
                'base_url': self.base_url,
                'lang': self.lang,
                'max_tokens': self.max_tokens,
                'temperature': self.temperature,
                'timeout': self.timeout}

    @property
    def source_tag(self):
        return f'ai:{self.provider}:{self.model}'


class TranslateResult:
    def __init__(self, ok, text='', source='', model='', error='', elapsed=0.0):
        self.ok = ok
        self.text = text
        self.source = source
        self.model = model
        self.error = error
        self.elapsed = elapsed

    def to_dict(self):
        d = {'ok': self.ok, 'elapsed': round(self.elapsed, 2)}
        if self.ok:
            d.update(text=self.text, source=self.source, model=self.model)
        else:
            d['error'] = self.error
        return d


def load_config():
    """从 settings 表读取配置；无配置返回默认配置（不抛异常）。"""
    try:
        import db
        raw = db.get_setting(CONFIG_KEY)
        if raw:
            return AIConfig.from_dict(json.loads(raw))
    except Exception:
        pass
    return AIConfig()


def save_config(cfg):
    """持久化配置（api_key 明文存本地库，与用户本地数据同等保护级别）。"""
    import db
    if isinstance(cfg, AIConfig):
        d = cfg.to_dict(hide_key=False)
    else:
        d = dict(cfg or {})
    db.set_setting(CONFIG_KEY, json.dumps(d, ensure_ascii=False))
    return AIConfig.from_dict(d)


_LABEL_RE = re.compile(r'^(?:译文|翻译|中文翻译|英文翻译|translation|译文正文)\s*[:：]\s*', re.I)


def sanitize(text):
    """清洗模型输出：去围栏/标签/首尾引号/多余空白。

    返回清洗后的译文；输入为空或清洗后为空返回 ''（调用方视为失败）。
    """
    if not text or not isinstance(text, str):
        return ''
    t = text.strip()
    # 去 ``` 代码围栏（含 ```zh ... ``` 形式）
    if t.startswith('```'):
        t = re.sub(r'^```[a-zA-Z]*\s*', '', t)
        t = re.sub(r'\s*```\s*$', '', t)
        t = t.strip()
    # 去"翻译："类前缀（可能多行，只去首行前缀）
    lines = t.splitlines()
    if lines:
        lines[0] = _LABEL_RE.sub('', lines[0]).strip()
        t = '\n'.join(lines).strip()
    # 去首尾成对引号（直引号/弯引号/书名号保留——书名号可能是译文内容）
    if len(t) >= 2 and t[0] == t[-1] and t[0] in ('"', "'", '"', '"', '"', "'"):
        t = t[1:-1].strip()
    # 压缩 3+ 连续空行为双换行
    t = re.sub(r'\n{3,}', '\n\n', t)
    return t.strip()


def _mock_translate(text, lang):
    """离线可用的确定性 mock 翻译（仅用于测试/演示，不冒充真实译文）。"""
    tag = 'MOCK中译' if lang == 'zh' else 'MOCK-EN'
    return f'[{tag}] {text}'


def _build_payload(cfg, text):
    """按服务商拼请求体。

    星火 MaaS v2（https://maas.xfyun.cn/doc Chat API）：
    - max_tokens 已废弃 → 改用 max_completion_tokens；
    - temperature/top_p 固定值生效、文档明确建议不要显式传入 → 不传；
    - 其余服务商保持 OpenAI 兼容参数（max_tokens + temperature）。
    """
    payload = {'model': cfg.model,
               'messages': [{'role': 'system', 'content': DEFAULT_PROMPTS[cfg.lang]},
                            {'role': 'user', 'content': text}],
               'stream': False}
    if cfg.provider == 'spark':
        payload['max_completion_tokens'] = cfg.max_tokens
    else:
        payload['max_tokens'] = cfg.max_tokens
        payload['temperature'] = cfg.temperature
    return payload


def translate_text(text, config=None, _http_post=None):
    """翻译单条日语句子。

    config: AIConfig（None 则从库里读）。_http_post 仅测试注入。
    在线 Provider 任何失败都返回 ok=False（不静默回退 mock）。
    """
    cfg = config if isinstance(config, AIConfig) else AIConfig.from_dict(config)
    t0 = time.time()
    text = (text or '').strip()
    if not text:
        return TranslateResult(False, error='输入为空')
    if cfg.provider == 'mock':
        return TranslateResult(True, text=sanitize(_mock_translate(text, cfg.lang)),
                               source=cfg.source_tag, model=cfg.model,
                               elapsed=time.time() - t0)
    # ---- 在线 Provider（OpenAI 兼容协议） ----
    if not cfg.api_key:
        return TranslateResult(False, error=f'{cfg.provider} 未配置 API Key（请在 AI 翻译面板填写）')
    if not cfg.base_url:
        return TranslateResult(False, error=f'{cfg.provider} 未配置接口地址 base_url')
    url = cfg.base_url + '/chat/completions'
    payload = _build_payload(cfg, text)
    headers = {'Authorization': f'Bearer {cfg.api_key}', 'Content-Type': 'application/json'}
    try:
        if _http_post is not None:
            resp = _http_post(url, headers=headers, payload=payload, timeout=cfg.timeout)
            status, data = resp
        else:
            import requests
            r = requests.post(url, headers=headers, json=payload, timeout=cfg.timeout)
            status, data = r.status_code, r.json()
    except Exception as e:
        return TranslateResult(False, error=f'请求失败（{type(e).__name__}: {e}）',
                               elapsed=time.time() - t0)
    if status != 200:
        msg = (data.get('error', {}) or {}).get('message', '') if isinstance(data, dict) else ''
        return TranslateResult(False, error=f'接口返回 {status}：{msg or data}',
                               elapsed=time.time() - t0)
    # 星火业务错误码：HTTP 200 但 code != 0（其他服务商无 code 字段，不受影响）
    if isinstance(data, dict) and 'code' in data and data.get('code') not in (0, '0', None):
        return TranslateResult(
            False,
            error=f"星火业务错误 {data.get('code')}：{data.get('message') or '未知错误'}",
            elapsed=time.time() - t0)
    try:
        raw = data['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError):
        return TranslateResult(False, error=f'接口返回结构异常：{str(data)[:200]}',
                               elapsed=time.time() - t0)
    clean = sanitize(raw or '')
    if not clean:
        return TranslateResult(False, error='模型返回为空（清洗后无有效译文）',
                               elapsed=time.time() - t0)
    return TranslateResult(True, text=clean, source=cfg.source_tag,
                           model=cfg.model, elapsed=time.time() - t0)


def count_missing():
    """缺翻译例句数（translation 为 NULL 或纯空白）。"""
    import db
    with db.get_conn() as c:
        r = c.execute("SELECT COUNT(*) n FROM sentences "
                      "WHERE translation IS NULL OR TRIM(COALESCE(translation,''))=''").fetchone()
    return r['n']


def list_missing(limit=50):
    """列出缺翻译例句（id, text），按 id 升序。"""
    import db
    with db.get_conn() as c:
        rows = c.execute("SELECT id, text FROM sentences "
                         "WHERE translation IS NULL OR TRIM(COALESCE(translation,''))='' "
                         "ORDER BY id ASC LIMIT ?", (max(1, int(limit or 50)),)).fetchall()
    return [dict(r) for r in rows]


def save_translation(sid, translation, source_tag):
    """保存译文 + 来源标记；translation 为空串则拒绝写入。"""
    translation = (translation or '').strip()
    if not translation:
        return False
    import db
    with db._lock, db.get_conn() as c:
        c.execute('UPDATE sentences SET translation=?, translation_source=? WHERE id=?',
                  (translation, source_tag, sid))
        return c.total_changes > 0


def batch_translate_missing(limit=20, config=None, progress_cb=None, _http_post=None):
    """批量补译缺翻译例句：逐条翻译→清洗→落库（失败跳过）。

    返回 {'total','done','failed','skipped','errors':[{id,error}...]}。
    progress_cb(done, total) 进度回调（路由层可用于 SSE/轮询，可选）。
    """
    cfg = config if isinstance(config, AIConfig) else AIConfig.from_dict(config)
    rows = list_missing(limit)
    total = len(rows)
    done, failed, errors = 0, 0, []
    for i, r in enumerate(rows):
        res = translate_text(r['text'], cfg, _http_post=_http_post)
        if res.ok and save_translation(r['id'], res.text, res.source):
            done += 1
        else:
            failed += 1
            errors.append({'id': r['id'],
                           'error': res.error if not res.ok else '写入失败'})
        if progress_cb:
            try:
                progress_cb(i + 1, total)
            except Exception:
                pass
    return {'total': total, 'done': done, 'failed': failed,
            'skipped': 0, 'errors': errors[:20]}
