# -*- coding: utf-8 -*-
"""写作/口语表现性任务。

选择题不能推断产出能力。本模块提供 Can-do 对齐的任务、约束和分析量规；
只接受人评/自评，不用关键词命中冒充语言能力评分。
"""
import json
import random
import time
import uuid
import db

RUBRICS = {
    'writing': [
        {'id':'task','label':'任务完成','weight':25,'bands':[
            '偏离任务或关键信息严重缺失','完成部分目的，但信息或理由不足','完成全部目的，信息具体且相关','充分完成目的，并能预见读者需求、有效补充和取舍信息']},
        {'id':'organization','label':'组织与衔接','weight':20,'bands':[
            '句子孤立，结构难以追踪','基本顺序可辨，衔接手段有限','段落与逻辑关系清楚，衔接自然','结构服务于论证，照应、推进和重点安排成熟']},
        {'id':'lexicogrammar','label':'词汇与语法','weight':25,'bands':[
            '错误频繁妨碍理解','常用形式基本可懂，复杂表达不稳定','词汇较准确多样，复杂句总体可控','用词精确、句式灵活，错误少且不影响文体效果']},
        {'id':'sociolinguistic','label':'语体与社会语言适切性','weight':20,'bands':[
            '称呼、待遇或文体明显不合场景','基本意识到关系与场合，但混用较多','待遇、文体和格式符合对象与目的','能细致调节距离、立场和缓和策略']},
        {'id':'mechanics','label':'表记与格式','weight':10,'bands':[
            '表记/格式严重影响阅读','有若干错误但主体可读','汉字假名、标点与格式基本稳定','表记准确，格式有效支持信息获取']},
    ],
    'speaking': [
        {'id':'task','label':'任务完成与内容','weight':20,'bands':[
            '无法完成主要交际目的','完成部分目的，需较多协助','完成主要目的并给出相关细节','灵活完成目的并妥善处理意外变化']},
        {'id':'interaction','label':'互动管理','weight':20,'bands':[
            '难以维持轮次或回应','可做简单回应，修复策略有限','能接续、确认、澄清和协商','能自然管理轮次、修复误解并推动互动']},
        {'id':'discourse','label':'谈话组织','weight':15,'bands':[
            '多为孤立词句','可连接短句但展开有限','能形成清楚连贯的成段话语','重点突出，展开、例证与收束自然']},
        {'id':'lexicogrammar','label':'词汇与语法','weight':20,'bands':[
            '表达范围窄且错误妨碍理解','熟悉话题基本可懂','表达范围足够，复杂形式总体可控','表达精确灵活，能有效改述和细化']},
        {'id':'sociolinguistic','label':'社会语言与语用','weight':15,'bands':[
            '待遇与意图表达不合场景','基本礼貌但直接度或待遇不稳定','关系、礼貌与言外意图处理得当','能细致调节立场、距离、缓和和说服策略']},
        {'id':'delivery','label':'流畅度与可懂度','weight':10,'bands':[
            '停顿/发音使理解困难','有明显停顿但大意可懂','节奏较稳定，整体容易理解','流畅自然，语音语调有效支持意义']},
    ],
}

TASKS = [
 {'id':'n3-email-change','level':'N3','skill':'writing','genre':'邮件','minutes':20,'word_guide':'250–400字',
  'can_do':'能向熟悉的机构说明情况、提出请求并确认后续安排。',
  'situation':'你报名参加周六的日语交流会，但临时必须上班。给活动负责人田中写邮件。',
  'requirements':['说明无法参加的原因','询问能否改到下周','若不能更改，询问取消手续','使用合适的邮件称呼和结尾'],
  'complication':'负责人比你年长，而且这是你第一次与对方联系。'},
 {'id':'n2-workplace-proposal','level':'N2','skill':'writing','genre':'提案短文','minutes':35,'word_guide':'600–800字',
  'can_do':'能围绕实际问题比较方案、论证建议并回应潜在反对意见。',
  'situation':'公司准备在“完全远程办公”和“每周到岗三天”之间选择新制度。请向部门主管提交建议。',
  'requirements':['明确选择或提出折中方案','至少比较三个维度','使用具体例子或条件支持判断','回应一个可能的反对意见'],
  'complication':'团队同时包含新员工、育儿员工和需要现场设备的员工。'},
 {'id':'n1-source-synthesis','level':'N1','skill':'writing','genre':'资料综合评论','minutes':50,'word_guide':'900–1200字',
  'can_do':'能综合立场不同的资料，区分事实与主张，并形成有条件的判断。',
  'situation':'阅读教师提供的两篇同主题短文后，写一篇评论，说明两者共识、分歧及你认为各自成立的条件。',
  'requirements':['准确概括两篇文章而非逐句翻译','指出至少一个共识与两个分歧','评价证据的充分性','形成有保留条件的结论'],
  'complication':'不得把个人经验当作能够直接推翻资料的证据。'},
 {'id':'n3-service-roleplay','level':'N3','skill':'speaking','genre':'角色扮演','minutes':6,'word_guide':'准备1分钟＋互动5分钟',
  'can_do':'能说明服务问题、提出合理请求并对解决方案作出回应。',
  'situation':'你租的自行车刹车有问题。向店员说明经过，并协商更换或退款。',
  'requirements':['清楚说明问题和发现时间','提出希望的处理方式','回答店员追问','确认最终安排'],
  'complication':'店员最初表示当天没有同型号车辆。'},
 {'id':'n2-polite-refusal','level':'N2','skill':'speaking','genre':'职场角色扮演','minutes':8,'word_guide':'准备2分钟＋互动6分钟',
  'can_do':'能在上下关系中拒绝不合理安排，同时维护关系并提出替代方案。',
  'situation':'主管要求你今天加班完成报告，但你已有不能取消的医院预约。请与主管协商。',
  'requirements':['表明理解任务的重要性','说明无法接受原安排','提出可执行替代方案','回应主管的追问或异议'],
  'complication':'主管强调报告明早必须交给客户。'},
 {'id':'n1-seminar-defense','level':'N1','skill':'speaking','genre':'学术讨论','minutes':12,'word_guide':'陈述3分钟＋质疑应答9分钟',
  'can_do':'能提出结构化论点、界定主张范围，并在质疑中修正或捍卫立场。',
  'situation':'就“大学课程是否应原则上公开录播”作三分钟立场陈述，随后回答质疑。',
  'requirements':['界定讨论范围','提出主张和至少两条依据','承认限制或例外','在反例出现后澄清或修正论点'],
  'complication':'考官将从隐私、公平或学习效果中选择一个角度提出反例。'},
]


def list_tasks(skill=None, level=None):
    return [t for t in TASKS if (not skill or t['skill']==skill) and (not level or t['level']==level)]


def make_task(skill=None, level=None, seed=None):
    pool = list_tasks(skill, level)
    if not pool: return {'ok':False,'error':'没有符合条件的表现性任务'}
    task = dict(random.Random(seed if seed is not None else time.time_ns()).choice(pool))
    task['instance_id'] = uuid.uuid4().hex
    task['rubric'] = RUBRICS[task['skill']]
    task['scoring_note'] = '各维度0–3级，由受训评分者依据实际表现评分；AI建议不得直接作为高风险最终分。'
    return {'ok':True,'task':task}


def validate_ratings(skill, ratings):
    rubric = {r['id']:r for r in RUBRICS.get(skill, [])}; clean={}; errors=[]
    for rid, spec in rubric.items():
        try: score=int((ratings or {}).get(rid))
        except (TypeError,ValueError): errors.append(f'{rid}: missing'); continue
        if score not in range(4): errors.append(f'{rid}: must be 0..3'); continue
        clean[rid]=score
    weighted = round(sum(clean[k]/3*rubric[k]['weight'] for k in clean),1) if not errors else None
    return clean, weighted, errors


def record_rating(task_id, instance_id, skill, ratings, rater='self', notes=''):
    clean, total, errors=validate_ratings(skill,ratings)
    if errors:return {'ok':False,'errors':errors}
    try: history=json.loads(db.get_setting('performance_ratings_v1','[]') or '[]')
    except Exception: history=[]
    history.append({'task_id':task_id,'instance_id':instance_id,'skill':skill,'ratings':clean,
                    'total':total,'rater':'teacher' if rater=='teacher' else 'self',
                    'notes':str(notes)[:1000],'timestamp':time.time()})
    db.set_setting('performance_ratings_v1',json.dumps(history[-500:],ensure_ascii=False))
    db.log('performance_rating',f'{skill}表现任务评分：{total}/100')
    return {'ok':True,'total':total,'ratings':clean,
            'interpretation':'量规维度反馈，不与客观题相加为单一总能力分'}
