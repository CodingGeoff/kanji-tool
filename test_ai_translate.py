#!/usr/bin/env python3
"""AI 翻译专项测试（v18）：清洗 / mock / 在线错误不静默降级 / 落库标记 / 批量。

全部用注入式 fake HTTP + 临时库，不碰真实网络与真实数据。
运行：python3 test_ai_translate.py"""
import json
import os
import sys
import tempfile

import ai_translate
from ai_translate import AIConfig, sanitize


def _fake_ok(url, headers, payload, timeout):
    assert url.endswith('/chat/completions'), url
    assert headers['Authorization'].startswith('Bearer sk-'), '缺失鉴权头'
    assert payload['model'] == 'deepseek-chat'
    assert any(m['role'] == 'user' for m in payload['messages'])
    return (200, {'choices': [{'message': {
        'content': '```zh\n翻译：春天来了。\n```'}}]})


def _fake_500(url, headers, payload, timeout):
    return (500, {'error': {'message': 'boom'}})


def _fake_empty(url, headers, payload, timeout):
    return (200, {'choices': [{'message': {'content': '```\n```'}}]})


def _fake_spark(url, headers, payload, timeout):
    """按星火 MaaS v2 文档校验请求体、返回真实形状的响应。"""
    assert url == 'https://maas-api.cn-huabei-1.xf-yun.com/v2/chat/completions', url
    assert headers['Authorization'] == 'Bearer ak-fake', '鉴权头异常'
    assert payload['model'] == 'spark-x2.5-4b', payload.get('model')
    assert payload['stream'] is False
    assert 'temperature' not in payload and 'top_p' not in payload, '星火不应传 temperature/top_p'
    assert 'max_tokens' not in payload, '星火 max_tokens 已废弃'
    assert payload['max_completion_tokens'] == 500, payload
    assert [m['role'] for m in payload['messages']] == ['system', 'user']
    user = payload['messages'][1]['content']
    return (200, {'code': 0, 'message': 'success', 'id': 'chatcmpl-fake',
                  'object': 'chat.completion', 'created': 1726000000,
                  'model': 'spark-x2.5-4b',
                  'choices': [{'index': 0, 'finish_reason': 'stop',
                               'message': {'role': 'assistant', 'content': f'春天来了。{user[:0]}',
                                           'reasoning_content': None}}],
                  'usage': {'prompt_tokens': 20, 'completion_tokens': 6, 'total_tokens': 26}})


def _fake_spark_bizerr(url, headers, payload, timeout):
    return (200, {'code': 130003, 'message': 'Quota exceeded'})


def _fake_boom(url, headers, payload, timeout):
    raise ConnectionError('offline')


def main():
    n_ok, fails = 0, []

    def check(name, cond, extra=''):
        nonlocal n_ok
        if cond:
            n_ok += 1
            print(f'  [OK]   {name}')
        else:
            fails.append(name)
            print(f'  FAIL: {name} {extra}')

    print('== 清洗 sanitize ==')
    check('去围栏+标签', sanitize('```zh\n翻译：春天来了。\n```') == '春天来了。')
    check('去Translation前缀', sanitize('Translation: It is spring.') == 'It is spring.')
    check('去首尾引号', sanitize('"你好。"') == '你好。')
    check('空输入', sanitize('') == '' and sanitize(None) == '')
    check('围栏掏空', sanitize('```\n```') == '')
    check('正常译文不动', sanitize('今日はいい天気です。') == '今日はいい天気です。')

    print('== 配置 ==')
    cfg = AIConfig.from_dict({'provider': 'nope', 'lang': 'fr'})
    check('非法provider回退星火', cfg.provider == 'spark' and cfg.lang == 'zh')
    dft = AIConfig()
    check('默认星火v2', dft.provider == 'spark' and dft.model == 'spark-x2.5-4b'
          and dft.base_url == 'https://maas-api.cn-huabei-1.xf-yun.com/v2', dft.to_dict())
    check('来源标记', AIConfig('spark', model='spark-max').source_tag == 'ai:spark:spark-max')
    check('key打码', AIConfig(api_key='sk-1').to_dict()['api_key'] == '***')

    print('== mock 翻译 ==')
    r = ai_translate.translate_text('春が来た。', AIConfig('mock', lang='zh'))
    check('mock成功', r.ok and '春が来た' in r.text and r.source == 'ai:mock:mock-v1', r.to_dict())
    r = ai_translate.translate_text('   ', AIConfig('mock'))
    check('空输入失败', not r.ok)

    print('== 在线分支（fake HTTP）==')
    online = AIConfig('deepseek', model='deepseek-chat', api_key='sk-test')
    r = ai_translate.translate_text('春が来た。', online, _http_post=_fake_ok)
    check('成功清洗落库格式', r.ok and r.text == '春天来了。' and r.source == 'ai:deepseek:deepseek-chat',
          r.to_dict())
    r = ai_translate.translate_text('春が来た。', AIConfig('deepseek', api_key=''))
    check('无key明确报错', not r.ok and 'API Key' in r.error, r.error)
    r = ai_translate.translate_text('春が来た。', online, _http_post=_fake_500)
    check('500不降级mock', not r.ok and '500' in r.error and 'MOCK' not in (r.text or ''), r.error)
    r = ai_translate.translate_text('春が来た。', online, _http_post=_fake_empty)
    check('空返回视为失败', not r.ok and '为空' in r.error, r.error)
    r = ai_translate.translate_text('春が来た。', online, _http_post=_fake_boom)
    check('断网明确报错', not r.ok and 'ConnectionError' in r.error, r.error)

    print('== 星火 v2 分支（fake HTTP，按官方文档形状）==')
    spark = AIConfig('spark', model='spark-x2.5-4b', api_key='ak-fake')
    r = ai_translate.translate_text('春が来た。', spark, _http_post=_fake_spark)
    check('星火请求体/响应解析', r.ok and r.text == '春天来了。'
          and r.source == 'ai:spark:spark-x2.5-4b', r.to_dict())
    r = ai_translate.translate_text('春が来た。', spark, _http_post=_fake_spark_bizerr)
    check('星火业务错误码', not r.ok and '130003' in r.error and 'Quota' in r.error, r.error)

    print('== 落库 + 批量（临时库）==')
    import db
    tmp = tempfile.mkdtemp(prefix='aitr_')
    old_path, old_lock = db.DB_PATH, db._lock
    try:
        import threading
        db.DB_PATH = os.path.join(tmp, 't.db')
        db._lock = threading.Lock()
        db.init_db()
        db._migrate()
        cols = [r[1] for r in
                __import__('sqlite3').connect(db.DB_PATH).execute('PRAGMA table_info(sentences)')]
        check('迁移补列', 'translation_source' in cols, str(cols))
        s1 = db.add_sentence('春が来た。', None, 'test', None, [], [])
        s2 = db.add_sentence('夏が来た。', '夏天来了。', 'test', None, [], [])
        check('缺译计数', ai_translate.count_missing() == 1, str(ai_translate.count_missing()))
        check('缺译列表', [x['id'] for x in ai_translate.list_missing()] == [s1])
        check('query缺译筛选', db.query_sentences(missing_trans=True)[0] == 1)
        check('空译文拒绝写入', ai_translate.save_translation(s1, '  ', 'ai:mock:m') is False)
        check('保存打标记', ai_translate.save_translation(s1, '春天来了。', 'ai:mock:mock-v1') is True)
        with db.get_conn() as c:
            row = dict(c.execute('SELECT translation,translation_source FROM sentences WHERE id=?',
                                 (s1,)).fetchone())
        check('标记落库', row == {'translation': '春天来了。',
                                 'translation_source': 'ai:mock:mock-v1'}, str(row))
        # 批量：再造 2 条缺译，一条成功一条失败（fake 按内容区分）
        s3 = db.add_sentence('秋が来た。', None, 'test', None, [], [])
        s4 = db.add_sentence('FAILME冬が来た。', None, 'test', None, [], [])

        def _fake_mix(url, headers, payload, timeout):
            user = next(m['content'] for m in payload['messages'] if m['role'] == 'user')
            if 'FAILME' in user:
                return (429, {'error': {'message': 'rate limit'}})
            return (200, {'choices': [{'message': {'content': f'译:{user}'}}]})

        stat = ai_translate.batch_translate_missing(
            limit=10, config=AIConfig('deepseek', api_key='sk-x'), _http_post=_fake_mix)
        check('批量1成1败', stat['done'] == 1 and stat['failed'] == 1 and stat['total'] == 2, str(stat))
        check('失败条保持缺译', ai_translate.count_missing() == 1)
        with db.get_conn() as c:
            ok_row = dict(c.execute('SELECT translation,translation_source FROM sentences WHERE id=?',
                                    (s3,)).fetchone())
        check('成功条来源', ok_row['translation_source'] == 'ai:deepseek:deepseek-chat'
              and ok_row['translation'] == '译:秋が来た。', str(ok_row))
        # 配置持久化
        ai_translate.save_config(AIConfig('spark', model='spark-x', api_key='sk-s', lang='en'))
        back = ai_translate.load_config()
        check('配置 round-trip', back.provider == 'spark' and back.model == 'spark-x'
              and back.api_key == 'sk-s' and back.lang == 'en')
    finally:
        db.DB_PATH, db._lock = old_path, old_lock

    print('== 路由（Flask test client + 临时库）==')
    import app as appmod
    old_path2 = db.DB_PATH
    try:
        db.DB_PATH = os.path.join(tmp, 't.db')
        db.init_db()
        db._migrate()
        cli = appmod.app.test_client()
        check('版本v18', cli.get('/api/version').json['version'] == 'v18')
        check('配置读取', cli.get('/api/translate/config').json['config']['provider'] == 'spark')
        r = cli.post('/api/translate/config', json={'provider': 'mock', 'lang': 'zh'})
        check('配置保存', r.json['ok'] and r.json['config']['provider'] == 'mock')
        cli.post('/api/translate/config',
                 json={'provider': 'deepseek', 'api_key': 'sk-keep', 'model': 'deepseek-chat'})
        check('打码回传保key', cli.post(
            '/api/translate/config',
            json={'provider': 'deepseek', 'api_key': '***', 'model': 'deepseek-chat'}).status_code == 200
              and ai_translate.load_config().api_key == 'sk-keep'
              and cli.get('/api/translate/config').json['config']['api_key'] == '***')
        cli.post('/api/translate/config', json={'provider': 'mock', 'lang': 'zh'})
        check('缺译接口', cli.get('/api/translate/missing').json['count'] == 1)
        r = cli.post('/api/translate/one', json={'text': '雪が降る。'})
        check('单条mock', r.json['ok'] and 'MOCK' in r.json['text'], str(r.json)[:120])
        r = cli.post('/api/translate/batch-missing', json={'limit': 5})
        check('批量mock清零', r.json['ok'] and r.json['done'] == 1
              and r.json['missing_left'] == 0, str(r.json)[:200])
        check('缺译筛选路由', cli.get('/api/sentences?missing_trans=1&per=50').json['total'] == 0)
    finally:
        db.DB_PATH = old_path2

    print(f'\n===== AI翻译专项测试: 通过 {n_ok} / {n_ok + len(fails)} =====')
    return 0 if not fails else 1


if __name__ == '__main__':
    sys.exit(main())
