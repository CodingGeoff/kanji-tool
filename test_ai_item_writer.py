# -*- coding: utf-8 -*-
"""AI 起草题目（ai_item_writer.py）专项测试
================================================================
全部用注入式 fake HTTP + mock provider + 临时库，不碰真实网络/真实数据。

覆盖：
  1. 没有译文的句子拒绝生成（没有语义锚点，AI 编的题无法核验）
  2. 在线 Provider 未配置 key / 网络失败 / 返回非法 JSON / 结构不合法 /
     证据栏文不对题 —— 一律不落库、如实报错，绝不静默降级
  3. 合法输出：落库 status 强制为 draft，字段完整
  4. mock provider：离线可用，明确标注 [MOCK]，不冒充真实质量
  5. 段落题：证据标签必须落在真实句序范围内
  6. 复核生命周期：draft→approved 必须完成全部检查项；未完成则拒绝
  7. draft_batch：Provider 级致命错误立即中止，不会"跳过继续"掩盖问题
  8. approved_items 只返回真正 approved 的题
"""
import os
import sys
import json
import shutil
import sqlite3
import tempfile

sys.path.insert(0, '.')

FAILS = []


def check(cond, msg):
    if cond:
        return True
    FAILS.append(msg)
    print('  FAIL:', msg)
    return False


import db
tmp = tempfile.mkdtemp()
api_db = os.path.join(tmp, 'kanji.db')
shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kanji.db'), api_db)
with sqlite3.connect(api_db) as c0:
    c0.execute("DELETE FROM settings WHERE key='ai_translate_config'")
db.DB_PATH = api_db

import ai_translate
import ai_item_writer as aw

TEXT = '彼女は明日、京都へ出張に行く予定だ。'
TR = '她计划明天去京都出差。'


def cfg(provider='deepseek', api_key='sk-fake'):
    return ai_translate.AIConfig(provider=provider, api_key=api_key, base_url='https://api.deepseek.com/v1')


print('== 1. 没有译文拒绝生成 ==')
r = aw.generate_sentence_item(1, TEXT, '', config=cfg())
check(r['ok'] is False and '译文' in r['error'], f'无译文应拒绝：{r}')

print('== 2. Provider 未配置 key ==')
r = aw.generate_sentence_item(1, TEXT, TR, config=cfg(api_key=''))
check(r['ok'] is False and 'API Key' in r['error'], f'未配置 key 应报错：{r}')

print('== 3. 网络失败 ==')


def _boom(url, headers, payload, timeout):
    raise ConnectionError('offline')


r = aw.generate_sentence_item(1, TEXT, TR, config=cfg(), _http_post=_boom)
check(r['ok'] is False and '请求失败' in r['error'], f'网络失败应报错：{r}')

print('== 4. 返回非法 JSON ==')


def _bad_json(url, headers, payload, timeout):
    return (200, {'choices': [{'message': {'content': '这不是JSON'}}]})


r = aw.generate_sentence_item(1, TEXT, TR, config=cfg(), _http_post=_bad_json)
check(r['ok'] is False and 'JSON' in r['error'], f'非法 JSON 应报错：{r}')
check(db.count_ai_drafts('listening') == {}, '非法输出绝不落库')

print('== 5. 结构不合法（选项不是 4 个）==')


def _bad_options(url, headers, payload, timeout):
    body = json.dumps({'process': 'detail', 'prompt': 'q?', 'options': ['a', 'b'], 'answer': 0,
                       'rationale': '依据 京都 出差'}, ensure_ascii=False)
    return (200, {'choices': [{'message': {'content': body}}]})


r = aw.generate_sentence_item(1, TEXT, TR, config=cfg(), _http_post=_bad_options)
check(r['ok'] is False and 'options_invalid' in r['error'], f'选项数不对应报错：{r}')

print('== 6. 证据栏文不对题（rationale 与原文/译文无关）==')


def _ungrounded(url, headers, payload, timeout):
    body = json.dumps({'process': 'detail', 'prompt': 'q?',
                       'options': ['正确项', '干扰1', '干扰2', '干扰3'], 'answer': 0,
                       'rationale': '因为苹果是红色的水果'}, ensure_ascii=False)
    return (200, {'choices': [{'message': {'content': body}}]})


r = aw.generate_sentence_item(1, TEXT, TR, config=cfg(), _http_post=_ungrounded)
check(r['ok'] is False and 'rationale_not_grounded' in r['error'], f'证据不落地应报错：{r}')

print('== 7. 合法输出：落库为 draft，字段完整 ==')


def _good(url, headers, payload, timeout):
    assert '京都' in payload['messages'][1]['content']
    body = json.dumps({'process': 'infer', 'prompt': '她明天要去哪里出差？',
                       'options': ['京都', '大阪', '东京', '奈良'], 'answer': 0,
                       'rationale': '原文「京都へ出張に行く」，译文「去京都出差」'}, ensure_ascii=False)
    return (200, {'choices': [{'message': {'content': f'```json\n{body}\n```'}}]})


r = aw.generate_sentence_item(42, TEXT, TR, source='tatoeba', level='N3', config=cfg(), _http_post=_good)
check(r['ok'] is True, f'合法输出应成功：{r}')
draft_id = r['draft_id']
d = aw.get_draft(draft_id)
check(d['status'] == 'draft', f'新起草题必须是 draft 状态：{d["status"]}')
check(d['payload']['items'][0]['answer'] == 0, '题目内容正确落库')
check(d['payload']['source']['kind'] == 'ai_generated' and d['payload']['source']['based_on_sid'] == 42,
      f'来源标注完整可溯源：{d["payload"]["source"]}')

print('== 8. mock provider：离线可用且明确标注 [MOCK] ==')
r = aw.generate_sentence_item(1, TEXT, TR, config=cfg(provider='mock'))
check(r['ok'] is True and '[MOCK]' in r['payload']['items'][0]['prompt'],
      f'mock 应明确标注，不冒充真实质量：{r}')

print('== 9. 段落题：证据标签必须落在真实句序范围内 ==')
PASSAGE = '京都は日本で人気の観光地だ。\n多くの寺や神社がある。\n特に紅葉の季節は観光客で賑わう。'


def _passage_good(url, headers, payload, timeout):
    body = json.dumps({'items': [
        {'process': 'main_idea', 'evidence': ['s1', 's99'], 'prompt': '这段话主要在说什么？',
         'options': ['京都是热门旅游地', '东京很拥挤', '奈良的鹿很多', '大阪的美食'],
         'answer': 0, 'rationale': '第一句「京都は日本で人気の観光地だ」点明主旨'},
    ]}, ensure_ascii=False)
    return (200, {'choices': [{'message': {'content': body}}]})


r = aw.generate_passage_item(PASSAGE, sids=[1, 2, 3], title='京都観光', config=cfg(),
                             _http_post=_passage_good)
check(r['ok'] is True, f'段落题应成功：{r}')
ev = r['payload']['items'][0]['evidence']
check(ev == ['s1'], f'越界的证据标签（s99）必须被过滤掉，只留真实存在的 s1：{ev}')

print('== 10. 复核生命周期：approve 前必须完成全部检查项 ==')
r = aw.review_draft(draft_id, 'approved', 'me', checklist={'content_correct': True})
check(r['ok'] is False and 'missing' in r, f'未完成全部检查项应拒绝 approve：{r}')
r = aw.review_draft(draft_id, 'approved', 'me', checklist={
    'content_correct': True, 'grounded_in_source': True, 'level_fit': True, 'language_natural': True})
check(r['ok'] is True, f'完成全部检查项应能 approve：{r}')
d2 = aw.get_draft(draft_id)
check(d2['status'] == 'approved' and d2['reviewer'] == 'me', f'复核状态落库：{d2}')

print('== 11. approved_items 只返回真正 approved 的题 ==')
items = aw.approved_items('listening')
check(len(items) == 1 and items[0]['id'] == draft_id, f'只应看到已批准的题：{[i["id"] for i in items]}')

print('== 12. draft_batch：Provider 致命错误立即中止 ==')
r = aw.draft_batch(n=3, kind='sentence', config=cfg(api_key=''))
check(r['ok'] is False and 'API Key' in r['error'], f'无 key 应立即中止整批：{r}')

print()
if FAILS:
    print(f'===== AI 起草题目测试: {len(FAILS)} 项失败 =====')
    sys.exit(1)
else:
    print('===== AI 起草题目测试: 全部通过 =====')

shutil.rmtree(tmp, ignore_errors=True)
