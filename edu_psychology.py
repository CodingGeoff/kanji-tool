# -*- coding: utf-8 -*-
"""
完整教育心理学模块（v16）- 深度整合教育心理学理论到自适应学习系统
====================================================================
理论框架：
1. 行为主义：强化、反馈时机、程序教学
2. 认知主义：信息加工、记忆模型、图式理论、认知负荷理论
3. 建构主义：最近发展区(ZPD)、支架式教学、主动学习
4. 人本主义：自我决定理论、需求层次、自我效能
5. 社会学习：观察学习、自我调节
6. 元认知：元认知监控、自我解释

核心功能：
- 学习者建模：IRT能力估计 + BKT知识追踪 + 工作记忆估计
- ZPD计算与推荐
- 认知负荷管理
- 布鲁姆分类法分级
- 支架式教学与渐退
- 元认知校准
- 错误分析与补救
- 动机与心流
- 学习分析仪表盘
- 自适应间隔重复整合
"""

import json
import math
import random
import time
from datetime import datetime, timedelta
from collections import defaultdict, Counter
import db
import grammar

# ================================================================
# 常量与配置
# ================================================================

# IRT参数
IRT_DEFAULT_A = 1.0  # 区分度
IRT_DEFAULT_B = 0.0  # 难度，0为中等，负为简单，正为困难
IRT_THETA_INIT = 0.0
IRT_THETA_MIN, IRT_THETA_MAX = -3.0, 3.0

# BKT参数
BKT_DEFAULT = {
    'p_init': 0.1,   # 初始掌握概率
    'p_learn': 0.3,  # 学习率
    'p_guess': 0.2,  # 猜测
    'p_slip': 0.1,   # 失误
}

# 布鲁姆层级
BLOOM_LEVELS = {
    'remember': {'order': 0, 'label': '记忆', 'desc': '回忆事实、术语、基本概念'},
    'understand': {'order': 1, 'label': '理解', 'desc': '解释、举例、分类、总结'},
    'apply': {'order': 2, 'label': '应用', 'desc': '执行、实施、运用到新情境'},
    'analyze': {'order': 3, 'label': '分析', 'desc': '区分、组织、归因'},
    'evaluate': {'order': 4, 'label': '评价', 'desc': '检查、评判、辩护'},
    'create': {'order': 5, 'label': '创造', 'desc': '生成、计划、制作'},
}

# 认知负荷
COGNITIVE_LOAD_WEIGHTS = {
    'kanji_density': 0.25,
    'grammar_difficulty': 0.30,
    'sentence_length': 0.15,
    'clause_count': 0.15,
    'vocab_rarity': 0.15,
}

# 支架等级
SCAFFOLD_LEVELS = {
    'full': {'order': 0, 'label': '完全支架', 'furigana': True, 'translation': True, 'hint': True, 'explain': True},
    'high': {'order': 1, 'label': '高支架', 'furigana': True, 'translation': True, 'hint': False, 'explain': False},
    'medium': {'order': 2, 'label': '中支架', 'furigana': True, 'translation': False, 'hint': False, 'explain': False},
    'low': {'order': 3, 'label': '低支架', 'furigana': False, 'translation': False, 'hint': False, 'explain': False},
    'none': {'order': 4, 'label': '无支架', 'furigana': False, 'translation': False, 'hint': False, 'explain': False},
}

# ZPD
ZPD_DELTA_MIN, ZPD_DELTA_MAX = 0.2, 0.8
ZPD_OPTIMAL_DELTA = 0.5

# 心流
FLOW_CHANNEL_WIDTH = 0.6  # 心流通道宽度

# ================================================================
# 学习者画像
# ================================================================

def _load_learner_model():
    """从settings加载学习者模型"""
    try:
        raw = db.get_setting('edu_learner_model', '')
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return {
        'theta': {
            'overall': IRT_THETA_INIT,
            'kanji': IRT_THETA_INIT,
            'vocab': IRT_THETA_INIT,
            'grammar': IRT_THETA_INIT,
            'listening': IRT_THETA_INIT,
        },
        'bkt': {},  # kc -> {p_mastery, attempts, correct, p_learn, p_guess, p_slip}
        'working_memory': 0.7,  # 0-1
        'cognitive_capacity': 0.75,
        'motivation': 0.7,
        'self_efficacy': 0.65,
        'metacog_calibration': 0.6,  # 元认知校准度
        'learning_style': {
            'visual': 0.5,
            'auditory': 0.5,
            'reading': 0.6,
            'kinesthetic': 0.4,
        },
        'error_patterns': {},  # error_type -> count
        'bloom_mastery': {k: 0.0 for k in BLOOM_LEVELS},
        'flow_history': [],
        'goal_orientation': 'mastery',  # mastery vs performance
        'last_update': time.time(),
    }

def _save_learner_model(model):
    try:
        db.set_setting('edu_learner_model', json.dumps(model, ensure_ascii=False))
    except Exception:
        pass

def get_learner_profile():
    """获取学习者画像（脱敏）"""
    m = _load_learner_model()
    # 计算衍生指标
    total_attempts = sum(v.get('attempts', 0) for v in m.get('bkt', {}).values())
    avg_mastery = sum(v.get('p_mastery', 0) for v in m.get('bkt', {}).values()) / max(1, len(m.get('bkt', {})))
    return {
        'theta': m['theta'],
        'overall_ability': m['theta']['overall'],
        'ability_level': theta_to_level(m['theta']['overall']),
        'working_memory': m['working_memory'],
        'cognitive_capacity': m['cognitive_capacity'],
        'motivation': m['motivation'],
        'self_efficacy': m['self_efficacy'],
        'metacog_calibration': m['metacog_calibration'],
        'learning_style': m['learning_style'],
        'bloom_mastery': m['bloom_mastery'],
        'total_kcs': len(m.get('bkt', {})),
        'total_attempts': total_attempts,
        'avg_mastery': round(avg_mastery, 3),
        'error_patterns': m.get('error_patterns', {}),
        'goal_orientation': m.get('goal_orientation', 'mastery'),
        'zpd': calculate_zpd(m),
        'flow_state': estimate_flow_state(m),
    }

def theta_to_level(theta):
    """能力值转等级"""
    if theta < -1.5:
        return 'N5'
    elif theta < -0.5:
        return 'N4'
    elif theta < 0.5:
        return 'N3'
    elif theta < 1.5:
        return 'N2'
    else:
        return 'N1'

def level_to_theta(level):
    mapping = {'N5': -2.0, 'N4': -1.0, 'N3': 0.0, 'N2': 1.0, 'N1': 2.0}
    return mapping.get(level, 0.0)

# ================================================================
# IRT 能力估计
# ================================================================

def irt_probability(theta, a, b):
    """2PL IRT: P(correct) = 1/(1+exp(-a*(theta-b)))"""
    try:
        return 1.0 / (1.0 + math.exp(-a * (theta - b)))
    except OverflowError:
        return 0.0 if a * (theta - b) < 0 else 1.0

def irt_update_theta(theta, a, b, correct, lr=0.3):
    """简化的能力更新：梯度上升"""
    p = irt_probability(theta, a, b)
    # 梯度： (correct - p) * a
    grad = (1.0 if correct else 0.0) - p
    new_theta = theta + lr * a * grad
    return max(IRT_THETA_MIN, min(IRT_THETA_MAX, new_theta))

def estimate_ability_from_history(skill='overall'):
    """从历史答题估计能力"""
    model = _load_learner_model()
    # 从SRS和cloze统计综合
    try:
        with db.get_conn() as c:
            row = c.execute('SELECT SUM(ok) ok_sum, SUM(ng) ng_sum, AVG(stage) avg_stage FROM srs').fetchone()
            ok = row['ok_sum'] or 0
            ng = row['ng_sum'] or 0
            avg_stage = row['avg_stage'] or 0
            if ok + ng > 0:
                acc = ok / (ok + ng)
                # 映射到theta: acc 0.5->0, 0.9->2, 0.3->-1.5
                theta = (acc - 0.65) * 4.0 + (avg_stage - 3.5) * 0.3
                return max(IRT_THETA_MIN, min(IRT_THETA_MAX, theta))
    except Exception:
        pass
    return model['theta'].get(skill, IRT_THETA_INIT)

# ================================================================
# BKT 知识追踪
# ================================================================

def bkt_update(p_mastery, correct, p_learn=None, p_guess=None, p_slip=None):
    """标准BKT更新"""
    p_learn = p_learn if p_learn is not None else BKT_DEFAULT['p_learn']
    p_guess = p_guess if p_guess is not None else BKT_DEFAULT['p_guess']
    p_slip = p_slip if p_slip is not None else BKT_DEFAULT['p_slip']

    # 观测概率
    if correct:
        p_obs = p_mastery * (1 - p_slip) + (1 - p_mastery) * p_guess
        if p_obs == 0:
            p_post = p_mastery
        else:
            p_post = (p_mastery * (1 - p_slip)) / p_obs
    else:
        p_obs = p_mastery * p_slip + (1 - p_mastery) * (1 - p_guess)
        if p_obs == 0:
            p_post = p_mastery
        else:
            p_post = (p_mastery * p_slip) / p_obs

    # 学习转移
    p_next = p_post + (1 - p_post) * p_learn
    return max(0.0, min(1.0, p_next))

def update_knowledge_component(kc_id, correct, skill='grammar'):
    """更新单个知识点的BKT"""
    model = _load_learner_model()
    bkt = model.get('bkt', {})
    entry = bkt.get(kc_id)
    if not entry:
        entry = {
            'p_mastery': BKT_DEFAULT['p_init'],
            'attempts': 0,
            'correct': 0,
            'p_learn': BKT_DEFAULT['p_learn'],
            'p_guess': BKT_DEFAULT['p_guess'],
            'p_slip': BKT_DEFAULT['p_slip'],
            'skill': skill,
            'last_update': time.time(),
        }
    entry['attempts'] += 1
    if correct:
        entry['correct'] += 1
    entry['p_mastery'] = bkt_update(
        entry['p_mastery'], correct,
        entry['p_learn'], entry['p_guess'], entry['p_slip']
    )
    entry['last_update'] = time.time()
    bkt[kc_id] = entry
    model['bkt'] = bkt

    # 同时更新IRT能力
    # 将BKT掌握度映射到IRT难度
    theta = model['theta'].get(skill, IRT_THETA_INIT)
    # 假设题目难度b与kc难度相关，简化：b = 0
    new_theta = irt_update_theta(theta, IRT_DEFAULT_A, 0.0, correct, lr=0.15)
    model['theta'][skill] = new_theta
    # overall为加权平均
    skills = ['kanji', 'vocab', 'grammar', 'listening']
    vals = [model['theta'].get(s, 0) for s in skills if s in model['theta']]
    if vals:
        model['theta']['overall'] = sum(vals) / len(vals)

    _save_learner_model(model)
    return entry

def get_mastery(kc_id):
    model = _load_learner_model()
    entry = model.get('bkt', {}).get(kc_id)
    return entry['p_mastery'] if entry else BKT_DEFAULT['p_init']

# ================================================================
# ZPD 最近发展区
# ================================================================

def calculate_zpd(model=None):
    """计算最近发展区"""
    if model is None:
        model = _load_learner_model()
    theta = model['theta']['overall']
    return {
        'current': theta,
        'zpd_min': theta + ZPD_DELTA_MIN,
        'zpd_max': theta + ZPD_DELTA_MAX,
        'optimal': theta + ZPD_OPTIMAL_DELTA,
        'level_current': theta_to_level(theta),
        'level_optimal': theta_to_level(theta + ZPD_OPTIMAL_DELTA),
        'range_label': f"{theta_to_level(theta + ZPD_DELTA_MIN)} ~ {theta_to_level(theta + ZPD_DELTA_MAX)}",
    }

def is_in_zpd(difficulty_theta, learner_theta=None):
    """判断题目是否在ZPD"""
    if learner_theta is None:
        learner_theta = _load_learner_model()['theta']['overall']
    delta = difficulty_theta - learner_theta
    return ZPD_DELTA_MIN <= delta <= ZPD_DELTA_MAX

def recommend_zpd_difficulty(learner_theta=None):
    """推荐ZPD难度"""
    if learner_theta is None:
        learner_theta = _load_learner_model()['theta']['overall']
    optimal = learner_theta + ZPD_OPTIMAL_DELTA
    # 加入随机扰动以保持多样性
    jitter = random.uniform(-0.2, 0.2)
    return max(IRT_THETA_MIN, min(IRT_THETA_MAX, optimal + jitter))

# ================================================================
# 认知负荷理论
# ================================================================

def estimate_intrinsic_load(text, grammar_level='N4'):
    """估计内在认知负荷 0-1"""
    if not text:
        return 0.5
    # 因素1：句子长度
    length_score = min(1.0, len(text) / 60.0)
    # 因素2：汉字密度
    kanji_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    kanji_density = kanji_count / max(1, len(text))
    kanji_score = min(1.0, kanji_density * 2.5)
    # 因素3：语法难度
    level_order = {'N5': 0, 'N4': 1, 'N3': 2, 'N2': 3, 'N1': 4}
    grammar_score = level_order.get(grammar_level, 1) / 4.0
    # 因素4：从句数（按标点）
    clause_count = text.count('、') + text.count('，') + text.count(',') + 1
    clause_score = min(1.0, clause_count / 5.0)
    # 因素5：词汇稀有度（简化：长度>3的词越多越难）
    words = text.split()
    vocab_score = min(1.0, len([w for w in words if len(w) > 3]) / 10.0)

    load = (
        length_score * COGNITIVE_LOAD_WEIGHTS['sentence_length'] +
        kanji_score * COGNITIVE_LOAD_WEIGHTS['kanji_density'] +
        grammar_score * COGNITIVE_LOAD_WEIGHTS['grammar_difficulty'] +
        clause_score * COGNITIVE_LOAD_WEIGHTS['clause_count'] +
        vocab_score * COGNITIVE_LOAD_WEIGHTS['vocab_rarity']
    )
    return round(load, 3)

def estimate_extraneous_load(ui_settings=None):
    """估计外在负荷"""
    if ui_settings is None:
        ui_settings = {}
    # 默认为中等
    load = 0.4
    if ui_settings.get('furigana_density') == 'high':
        load += 0.1
    if ui_settings.get('show_translation'):
        load += 0.05
    if ui_settings.get('distractions'):
        load += 0.15
    return min(1.0, load)

def estimate_germane_load(explanation_length=0, has_example=False):
    """估计相关负荷（有益的）"""
    load = 0.2
    if explanation_length > 50:
        load += 0.15
    if has_example:
        load += 0.1
    return min(1.0, load)

def calculate_total_load(text, grammar_level='N4', ui_settings=None, explanation_length=0):
    intrinsic = estimate_intrinsic_load(text, grammar_level)
    extraneous = estimate_extraneous_load(ui_settings)
    germane = estimate_germane_load(explanation_length)
    total = intrinsic + extraneous * 0.5 + germane * 0.3  # 加权
    # 归一到0-1
    total = min(1.0, total / 1.5)
    return {
        'intrinsic': intrinsic,
        'extraneous': extraneous,
        'germane': germane,
        'total': round(total, 3),
        'level': 'low' if total < 0.4 else ('medium' if total < 0.7 else 'high'),
        'optimal': 0.4 <= total <= 0.7,
    }

def adjust_for_cognitive_load(questions, capacity=None):
    """根据认知负荷调整题目序列"""
    if capacity is None:
        capacity = _load_learner_model().get('cognitive_capacity', 0.75)
    # 按负荷排序，低->高，穿插
    scored = []
    for q in questions:
        load = calculate_total_load(q.get('text', ''), q.get('level', 'N4'))
        scored.append((load['total'], q))
    # 交错：先易后难再易，形成波浪
    scored.sort(key=lambda x: x[0])
    result = []
    low = [q for s, q in scored if s < 0.4]
    med = [q for s, q in scored if 0.4 <= s < 0.7]
    high = [q for s, q in scored if s >= 0.7]
    # 波浪： low, med, high, med, low ...
    pools = [low, med, high, med, low]
    idx = [0]*len(pools)
    # 轮询
    for _ in range(len(questions)):
        for p_i, pool in enumerate(pools):
            if idx[p_i] < len(pool):
                result.append(pool[idx[p_i]])
                idx[p_i] += 1
                break
    return result[:len(questions)]

# ================================================================
# 布鲁姆分类法
# ================================================================

def classify_bloom_level(question):
    """根据题目类型分类布鲁姆层级"""
    # 基于题目特征启发式分类
    name = question.get('name', '')
    text = question.get('text', '')
    # 简单规则
    if '〜' in name and 'だ' in name:
        return 'remember'
    if '条件' in name or '原因' in name:
        return 'understand'
    if len(question.get('options', [])) == 4:
        # 选择题：应用
        return 'apply'
    if 'のに' in name or 'ものの' in name:
        return 'analyze'
    if 'べき' in name or 'はず' in name:
        return 'evaluate'
    # 默认按难度
    level = question.get('level', 'N4')
    mapping = {'N5': 'remember', 'N4': 'understand', 'N3': 'apply', 'N2': 'analyze', 'N1': 'evaluate'}
    return mapping.get(level, 'apply')

def ensure_bloom_coverage(questions, target_distribution=None):
    """确保布鲁姆覆盖"""
    if target_distribution is None:
        # 默认：记忆30%，理解30%，应用25%，分析10%，评价5%
        target_distribution = {
            'remember': 0.3,
            'understand': 0.3,
            'apply': 0.25,
            'analyze': 0.1,
            'evaluate': 0.05,
            'create': 0.0,
        }
    # 统计当前
    counts = Counter(classify_bloom_level(q) for q in questions)
    total = len(questions)
    # 简单检查：如果某层级缺失，尝试从候选池补充（此处仅返回分析）
    coverage = {k: counts.get(k, 0)/max(1, total) for k in BLOOM_LEVELS}
    return {
        'counts': dict(counts),
        'coverage': coverage,
        'target': target_distribution,
        'balanced': all(abs(coverage.get(k,0)-target_distribution.get(k,0)) < 0.2 for k in target_distribution if target_distribution[k]>0),
    }

# ================================================================
# 支架式教学
# ================================================================

def recommend_scaffold_level(kc_id=None, p_mastery=None, theta=None):
    """推荐支架等级"""
    if p_mastery is None and kc_id:
        p_mastery = get_mastery(kc_id)
    if p_mastery is None:
        p_mastery = 0.3
    if p_mastery < 0.3:
        return 'full'
    elif p_mastery < 0.5:
        return 'high'
    elif p_mastery < 0.7:
        return 'medium'
    elif p_mastery < 0.9:
        return 'low'
    else:
        return 'none'

def fade_scaffold(history):
    """根据历史渐退支架"""
    # history: list of {correct, scaffold_level}
    if not history:
        return 'full'
    recent = history[-5:]
    acc = sum(1 for h in recent if h.get('correct')) / len(recent)
    if acc > 0.8:
        # 提升一级（减少支架）
        current = recent[-1].get('scaffold', 'full')
        order = SCAFFOLD_LEVELS[current]['order']
        levels = sorted(SCAFFOLD_LEVELS.items(), key=lambda x: x[1]['order'])
        if order < len(levels)-1:
            return levels[order+1][0]
        return current
    elif acc < 0.4:
        # 降低一级（增加支架）
        current = recent[-1].get('scaffold', 'medium')
        order = SCAFFOLD_LEVELS[current]['order']
        levels = sorted(SCAFFOLD_LEVELS.items(), key=lambda x: x[1]['order'])
        if order > 0:
            return levels[order-1][0]
        return current
    return recent[-1].get('scaffold', 'medium')

# ================================================================
# 元认知
# ================================================================

def record_confidence(kc_id, confidence, correct):
    """记录信心与实际，计算校准"""
    # confidence 0-1
    model = _load_learner_model()
    # 更新校准度： 1 - |confidence - correct|
    calibration = 1.0 - abs(confidence - (1.0 if correct else 0.0))
    # 指数移动平均
    alpha = 0.2
    old = model.get('metacog_calibration', 0.6)
    model['metacog_calibration'] = old * (1-alpha) + calibration * alpha
    # 记录到BKT扩展
    bkt = model.get('bkt', {})
    if kc_id in bkt:
        entry = bkt[kc_id]
        entry['confidence_history'] = entry.get('confidence_history', [])[-9:] + [{'conf': confidence, 'correct': correct, 'calib': calibration}]
        bkt[kc_id] = entry
    model['bkt'] = bkt
    _save_learner_model(model)
    return {
        'calibration': calibration,
        'overall_calibration': model['metacog_calibration'],
        'well_calibrated': calibration > 0.7,
        'overconfident': confidence > 0.7 and not correct,
        'underconfident': confidence < 0.4 and correct,
    }

def metacognitive_prompt(kc_id=None):
    """生成元认知提示"""
    prompts = [
        "为什么这个答案是正确的？试着用自己的话解释。",
        "这个语法点和你之前学过的哪个相似？区别是什么？",
        "你有多大把握？如果不确定，哪里不确定？",
        "如果让你教别人，你会怎么解释这个？",
        "这个错误反映了什么理解误区？",
        "下次遇到类似情况，你会怎么思考？",
    ]
    return random.choice(prompts)

# ================================================================
# 错误分析
# ================================================================

ERROR_TAXONOMY = {
    'grammar_confusion': '语法混淆（形近义近）',
    'particle_error': '助词错误',
    'conjugation_error': '活用错误',
    'vocab_choice': '词汇选择',
    'kanji_reading': '汉字读音',
    'context_mismatch': '语境不符',
    'overgeneralization': '过度泛化',
    'l1_interference': '母语干扰',
}

def analyze_error(question, chosen, correct):
    """分析错误类型"""
    if chosen == correct:
        return None
    name = question.get('name', '')
    # 启发式
    if 'て' in correct and 'て' in chosen:
        return 'grammar_confusion'
    if correct in ('は', 'が', 'を', 'に', 'で', 'へ') or chosen in ('は', 'が', 'を', 'に', 'で', 'へ'):
        return 'particle_error'
    if 'ない' in correct or 'れる' in correct or 'せる' in correct:
        return 'conjugation_error'
    if len(correct) > 2 and len(chosen) > 2:
        return 'vocab_choice'
    return 'grammar_confusion'

def record_error(error_type, kc_id=None):
    model = _load_learner_model()
    patterns = model.get('error_patterns', {})
    patterns[error_type] = patterns.get(error_type, 0) + 1
    model['error_patterns'] = patterns
    _save_learner_model(model)

def get_error_remediation(error_type):
    """获取补救建议"""
    remediations = {
        'grammar_confusion': {
            'strategy': '对比学习',
            'suggestion': '将混淆的语法点并列对比，关注核心区别',
            'exercise': '做对比填空，强化区分',
        },
        'particle_error': {
            'strategy': '图式强化',
            'suggestion': '回顾助词的核心意象和用法图式',
            'exercise': '助词专项练习，从核心意义出发',
        },
        'conjugation_error': {
            'strategy': '程序化练习',
            'suggestion': '分解活用步骤，逐步自动化',
            'exercise': '活用变形表 + 句子填空',
        },
        'vocab_choice': {
            'strategy': '语境学习',
            'suggestion': '关注词汇的语体、搭配和细微差别',
            'exercise': '语境中选词，关注搭配',
        },
        'kanji_reading': {
            'strategy': '多模态编码',
            'suggestion': '结合字形、读音、意义多通道记忆',
            'exercise': '汉字卡片 + 词汇扩展',
        },
        'context_mismatch': {
            'strategy': '语用意识',
            'suggestion': '关注说话人立场、礼貌度、语境',
            'exercise': '情景判断练习',
        },
        'overgeneralization': {
            'strategy': '边界意识',
            'suggestion': '明确规则的适用边界和例外',
            'exercise': '正例反例对比',
        },
        'l1_interference': {
            'strategy': '对比分析',
            'suggestion': '对比母语和日语的表达差异',
            'exercise': '翻译对比，关注差异',
        },
    }
    return remediations.get(error_type, remediations['grammar_confusion'])

# ================================================================
# 动机与心流
# ================================================================

def estimate_flow_state(model=None):
    """估计心流状态"""
    if model is None:
        model = _load_learner_model()
    theta = model['theta']['overall']
    # 最近准确率作为挑战感知
    try:
        stats = json.loads(db.get_setting('book_cloze_stats', '') or '{}')
        recent_days = sorted(stats.keys())[-3:]
        if recent_days:
            acc = sum(stats[d].get('correct',0) for d in recent_days) / max(1, sum(stats[d].get('asked',0) for d in recent_days))
            challenge = acc  # 简化：准确率低=挑战高
        else:
            challenge = 0.5
    except Exception:
        challenge = 0.5

    skill = (theta + 3) / 6.0  # 归一到0-1
    # 心流条件：挑战≈技能
    diff = abs(challenge - skill)
    if diff < 0.15:
        state = 'flow'
    elif challenge > skill + 0.2:
        state = 'anxiety'
    elif skill > challenge + 0.2:
        state = 'boredom'
    else:
        state = 'control'

    return {
        'state': state,
        'challenge': round(challenge, 2),
        'skill': round(skill, 2),
        'balance': round(1 - diff, 2),
        'label': {'flow': '心流', 'anxiety': '焦虑', 'boredom': '无聊', 'control': '控制感'}[state],
    }

def update_motivation(correct, time_spent=None, flow_state=None):
    """更新动机"""
    model = _load_learner_model()
    # 简单规则：正确+动机，错误-动机但有下限
    delta = 0.05 if correct else -0.03
    model['motivation'] = max(0.1, min(1.0, model.get('motivation', 0.7) + delta))
    # 自我效能：基于成功经验
    if correct:
        model['self_efficacy'] = max(0.1, min(1.0, model.get('self_efficacy', 0.65) + 0.04))
    else:
        model['self_efficacy'] = max(0.1, min(1.0, model.get('self_efficacy', 0.65) - 0.02))

    if flow_state:
        model['flow_history'] = (model.get('flow_history', [])[-19:] + [flow_state])

    _save_learner_model(model)

def recommend_motivational_feedback(correct, streak=0, error_type=None):
    """推荐动机性反馈"""
    if correct:
        if streak >= 5:
            return {'type': 'mastery', 'message': f'太棒了！连续答对{streak}题，你已经掌握了这个模式！', 'tone': 'celebratory'}
        elif streak >= 3:
            return {'type': 'competence', 'message': '连续正确，进步明显！', 'tone': 'encouraging'}
        else:
            return {'type': 'positive', 'message': '正确！保持这个势头', 'tone': 'positive'}
    else:
        remediation = get_error_remediation(error_type) if error_type else None
        if remediation:
            return {'type': 'corrective', 'message': f"别灰心，{remediation['suggestion']}", 'tone': 'supportive', 'remediation': remediation}
        return {'type': 'encouraging', 'message': '这个确实容易混淆，看看解析再试一次', 'tone': 'supportive'}

# ================================================================
# 学习分析仪表盘
# ================================================================

def get_learning_analytics(days=14):
    """获取学习分析数据"""
    model = _load_learner_model()
    profile = get_learner_profile()

    # SRS统计
    try:
        with db.get_conn() as c:
            srs_stats = c.execute('SELECT COUNT(*) total, SUM(CASE WHEN stage>=7 THEN 1 ELSE 0 END) mature, AVG(stage) avg_stage, SUM(ok) ok_sum, SUM(ng) ng_sum FROM srs').fetchone()
            srs_total = srs_stats['total'] or 0
            srs_mature = srs_stats['mature'] or 0
            srs_avg_stage = srs_stats['avg_stage'] or 0
            srs_ok = srs_stats['ok_sum'] or 0
            srs_ng = srs_stats['ng_sum'] or 0
    except Exception:
        srs_total = srs_mature = srs_avg_stage = srs_ok = srs_ng = 0

    # Cloze统计
    try:
        cloze_raw = json.loads(db.get_setting('book_cloze_stats', '') or '{}')
        cloze_days = sorted(cloze_raw.keys())[-days:]
        cloze_trend = [{'day': d, **cloze_raw[d]} for d in cloze_days]
        total_asked = sum(v.get('asked',0) for v in cloze_raw.values())
        total_correct = sum(v.get('correct',0) for v in cloze_raw.values())
        accuracy = total_correct / max(1, total_asked)
    except Exception:
        cloze_trend = []
        total_asked = total_correct = 0
        accuracy = 0.65

    # BKT掌握分布
    bkt = model.get('bkt', {})
    mastery_dist = {'0-0.3':0, '0.3-0.6':0, '0.6-0.9':0, '0.9-1.0':0}
    for v in bkt.values():
        pm = v.get('p_mastery', 0)
        if pm < 0.3:
            mastery_dist['0-0.3'] += 1
        elif pm < 0.6:
            mastery_dist['0.3-0.6'] += 1
        elif pm < 0.9:
            mastery_dist['0.6-0.9'] += 1
        else:
            mastery_dist['0.9-1.0'] += 1

    # 遗忘曲线预测（基于SRS）
    forgetting_curve = []
    for d in range(0, 30, 3):
        # 简化：回忆概率随时间衰减，掌握度越高衰减越慢
        avg_mastery = sum(v.get('p_mastery',0) for v in bkt.values()) / max(1, len(bkt)) if bkt else 0.5
        # 指数衰减：P = mastery * exp(-decay * t)
        decay = 0.05 * (1.5 - avg_mastery)  # 掌握高衰减慢
        recall = avg_mastery * math.exp(-decay * d)
        forgetting_curve.append({'day': d, 'recall': round(recall, 3)})

    # 错误分析
    error_dist = model.get('error_patterns', {})

    # 布鲁姆掌握
    bloom_mastery = model.get('bloom_mastery', {})

    return {
        'profile': profile,
        'srs': {
            'total': srs_total,
            'mature': srs_mature,
            'avg_stage': round(srs_avg_stage,2),
            'accuracy': round(srs_ok / max(1, srs_ok+srs_ng), 3) if (srs_ok+srs_ng)>0 else 0.65,
            'mature_rate': round(srs_mature / max(1, srs_total), 3),
        },
        'cloze': {
            'total_asked': total_asked,
            'total_correct': total_correct,
            'accuracy': round(accuracy,3),
            'trend': cloze_trend,
        },
        'mastery_distribution': mastery_dist,
        'forgetting_curve': forgetting_curve,
        'error_distribution': error_dist,
        'bloom_mastery': bloom_mastery,
        'zpd': profile.get('zpd'),
        'flow': profile.get('flow_state'),
        'recommendations': generate_recommendations(model, profile),
    }

def generate_recommendations(model, profile=None):
    """生成个性化学习建议"""
    if profile is None:
        profile = get_learner_profile()
    recs = []

    # 基于能力
    theta = profile['overall_ability']
    if theta < -1.0:
        recs.append({'type': 'level', 'priority': 'high', 'title': '巩固基础', 'desc': '建议多练习N5-N4基础语法和常用汉字，当前能力在初级阶段', 'action': '降低难度，增加课文比例'})
    elif theta > 1.5:
        recs.append({'type': 'level', 'priority': 'medium', 'title': '挑战高阶', 'desc': '能力已达N2-N1，可尝试更多N1语法和复杂句型', 'action': '提高难度，增加语料库和歌词多样性'})

    # 基于掌握度
    low_mastery = [k for k, v in model.get('bkt', {}).items() if v.get('p_mastery',0) < 0.4]
    if len(low_mastery) > 5:
        recs.append({'type': 'mastery', 'priority': 'high', 'title': f'{len(low_mastery)}个薄弱点需强化', 'desc': f"薄弱语法：{', '.join(low_mastery[:3])}...", 'action': '针对薄弱点专项练习'})

    # 基于错误
    error_patterns = profile.get('error_patterns', {})
    if error_patterns:
        top_error = max(error_patterns.items(), key=lambda x: x[1])[0] if error_patterns else None
        if top_error:
            remediation = get_error_remediation(top_error)
            recs.append({'type': 'error', 'priority': 'high', 'title': f"主要错误类型：{ERROR_TAXONOMY.get(top_error, top_error)}", 'desc': remediation['suggestion'], 'action': remediation['exercise']})

    # 基于心流
    flow = profile.get('flow_state', {})
    if flow.get('state') == 'anxiety':
        recs.append({'type': 'flow', 'priority': 'high', 'title': '难度过高，产生焦虑', 'desc': '挑战远高于技能，建议降低难度或增加支架', 'action': '降低难度，增加提示和翻译'})
    elif flow.get('state') == 'boredom':
        recs.append({'type': 'flow', 'priority': 'medium', 'title': '难度过低，感到无聊', 'desc': '技能高于挑战，建议提高难度', 'action': '提高难度，减少支架，增加新颖性'})

    # 基于认知负荷
    # 假设平均负荷高
    # recs.append(...)

    # 基于元认知
    calib = profile.get('metacog_calibration', 0.6)
    if calib < 0.5:
        recs.append({'type': 'metacog', 'priority': 'medium', 'title': '元认知校准需提升', 'desc': '对自己掌握程度的判断不够准确，建议答题前先评估信心', 'action': '启用信心评分，关注校准反馈'})

    # 动机
    motivation = profile.get('motivation', 0.7)
    if motivation < 0.5:
        recs.append({'type': 'motivation', 'priority': 'high', 'title': '动机下降', 'desc': '学习动机有所下降，建议设定小目标，关注进步', 'action': '设定可达成的小目标，记录进步'})

    if not recs:
        recs.append({'type': 'general', 'priority': 'low', 'title': '保持良好状态', 'desc': '各项指标良好，继续保持当前学习节奏', 'action': '维持当前配置，适度增加挑战'})

    return recs

# ================================================================
# 自适应出题整合教育心理学
# ================================================================

def recommend_quiz_config_psy(book_ids=None, learner_model=None):
    """整合教育心理学的推荐"""
    # 基础推荐
    import textbook
    base = textbook.recommend_quiz_config(book_ids)

    if learner_model is None:
        learner_model = _load_learner_model()
    profile = get_learner_profile()

    # ZPD调整
    zpd = calculate_zpd(learner_model)
    # 推荐难度
    rec_theta = recommend_zpd_difficulty(learner_model['theta']['overall'])
    rec_level = theta_to_level(rec_theta)

    # 认知负荷调整
    capacity = learner_model.get('cognitive_capacity', 0.75)
    # 容量低 -> 题量少
    if capacity < 0.5:
        base['total'] = max(3, int(base['total'] * 0.6))
    elif capacity > 0.85:
        base['total'] = min(40, int(base['total'] * 1.3))

    # 心流调整
    flow = estimate_flow_state(learner_model)
    if flow['state'] == 'anxiety':
        # 焦虑 -> 降低难度，增加支架
        base['ratios']['book'] = min(80, base['ratios']['book'] + 10)
        base['scaffold'] = 'high'
    elif flow['state'] == 'boredom':
        base['ratios']['corpus'] = min(50, base['ratios']['corpus'] + 10)
        base['ratios']['lyric'] = min(40, base['ratios']['lyric'] + 10)
        base['scaffold'] = 'low'

    # 布鲁姆分布
    bloom_target = {
        'remember': 0.25 if profile['overall_ability'] < 0 else 0.15,
        'understand': 0.30,
        'apply': 0.30,
        'analyze': 0.10 if profile['overall_ability'] > -0.5 else 0.05,
        'evaluate': 0.05 if profile['overall_ability'] > 0.5 else 0.0,
    }

    # 工作记忆调整
    wm = learner_model.get('working_memory', 0.7)
    if wm < 0.5:
        base['total'] = max(3, base['total'] - 2)
        base['interleaving'] = False  # 低工作记忆不适合高交错
    else:
        base['interleaving'] = True

    # 整合解释
    psy_explain = (
        f"[教育心理学] 能力θ={learner_model['theta']['overall']:.2f}({profile['ability_level']}) "
        f"ZPD最优{rec_level}({rec_theta:.2f}) 心流:{flow['label']} "
        f"认知容量{capacity:.2f} 工作记忆{wm:.2f} "
        f"元认知校准{profile['metacog_calibration']:.2f} 动机{profile['motivation']:.2f}"
    )

    base['psy'] = {
        'theta': learner_model['theta'],
        'zpd': zpd,
        'recommended_theta': rec_theta,
        'recommended_level': rec_level,
        'flow': flow,
        'cognitive_capacity': capacity,
        'working_memory': wm,
        'bloom_target': bloom_target,
        'scaffold': base.get('scaffold', recommend_scaffold_level()),
        'interleaving': base.get('interleaving', True),
    }
    base['explain'] = base.get('explain','') + ' | ' + psy_explain
    return base

def adaptive_cloze_multi(book_ids=None, total=None, ratios=None, difficulty=None,
                         learner_model=None, include_bloom=True, include_scaffold=True):
    """整合教育心理学的多源出题"""
    import textbook
    if learner_model is None:
        learner_model = _load_learner_model()

    # 基础出题
    result = textbook.make_cloze_multi(book_ids, total, ratios, difficulty)

    if not result.get('ok'):
        return result

    questions = result.get('questions', [])

    # 1. ZPD过滤与排序：优先ZPD内的题目
    theta = learner_model['theta']['overall']
    def _q_theta(q):
        return level_to_theta(q.get('level','N4'))
    # 计算每个题目与最优ZPD的距离
    optimal = theta + ZPD_OPTIMAL_DELTA
    scored = []
    for q in questions:
        q_th = _q_theta(q)
        dist = abs(q_th - optimal)
        # 加上掌握度惩罚：已掌握的降低优先级
        mastery = get_mastery(q.get('name',''))
        penalty = mastery * 0.5  # 掌握高惩罚
        scored.append((dist + penalty, q))
    scored.sort(key=lambda x: x[0])
    questions = [q for _, q in scored]

    # 2. 认知负荷交错
    questions = adjust_for_cognitive_load(questions, learner_model.get('cognitive_capacity'))

    # 3. 布鲁姆覆盖检查
    bloom_info = ensure_bloom_coverage(questions) if include_bloom else None

    # 4. 支架等级标注
    if include_scaffold:
        for q in questions:
            mastery = get_mastery(q.get('name',''))
            scaffold = recommend_scaffold_level(p_mastery=mastery)
            q['scaffold'] = scaffold
            q['scaffold_config'] = SCAFFOLD_LEVELS[scaffold]
            q['bloom'] = classify_bloom_level(q)
            q['cognitive_load'] = calculate_total_load(q.get('text',''), q.get('level','N4'))
            q['in_zpd'] = is_in_zpd(_q_theta(q), theta)
            q['mastery'] = round(mastery, 3)

    # 5. 间隔重复整合：优先到期SRS相关题目
    try:
        with db.get_conn() as c:
            due_kanji = set(r['kanji'] for r in c.execute('SELECT kanji FROM srs WHERE next_due <= ? LIMIT 100', (time.time(),)).fetchall())
        # 提升含到期汉字的题目
        def _has_due(q):
            txt = q.get('text','')
            return any(k in txt for k in due_kanji)
        questions.sort(key=lambda q: (0 if _has_due(q) else 1, 0 if q.get('in_zpd') else 1))
    except Exception:
        pass

    result['questions'] = questions
    result['psy'] = {
        'zpd_optimal': optimal,
        'learner_theta': theta,
        'bloom_coverage': bloom_info,
        'cognitive_load_avg': sum(calculate_total_load(q.get('text',''), q.get('level','N4'))['total'] for q in questions) / max(1, len(questions)),
    }
    return result

# ================================================================
# 自我调节学习
# ================================================================

def get_study_plan_srl(book_ids=None):
    """自我调节学习计划"""
    import textbook
    plan = textbook.build_plan(book_ids, save=False)
    model = _load_learner_model()

    # 加入SRL元素
    srl = {
        'forethought': {
            'goal_setting': f"目标：掌握{plan.get('new_total',0)}个新项，正确率{model.get('motivation',0.7)*100:.0f}%",
            'strategic_planning': "策略：间隔重复 + 检索练习 + 交错学习",
            'self_efficacy': model.get('self_efficacy', 0.65),
        },
        'performance': {
            'self_control': "执行：专注、时间管理、求助策略",
            'self_observation': "监控：记录答题时间、信心、错误类型",
        },
        'self_reflection': {
            'self_judgment': "评价：对比目标与实际，分析原因",
            'self_reaction': "调整：根据反馈调整策略",
        }
    }
    plan['srl'] = srl
    return plan

def record_study_session(session_data):
    """记录学习会话，用于分析"""
    # session_data: {duration, questions, correct, time_per_q, confidence, flow}
    try:
        raw = db.get_setting('edu_sessions', '[]')
        sessions = json.loads(raw) if raw else []
    except Exception:
        sessions = []
    session_data['timestamp'] = time.time()
    sessions.append(session_data)
    # 只保留最近100条
    sessions = sessions[-100:]
    db.set_setting('edu_sessions', json.dumps(sessions, ensure_ascii=False))
    return {'ok': True, 'count': len(sessions)}

def get_session_analytics():
    try:
        raw = db.get_setting('edu_sessions', '[]')
        sessions = json.loads(raw) if raw else []
    except Exception:
        sessions = []
    if not sessions:
        return {'ok': True, 'sessions': [], 'avg_duration': 0, 'avg_accuracy': 0}

    total_duration = sum(s.get('duration',0) for s in sessions)
    total_q = sum(len(s.get('questions',[])) for s in sessions)
    total_correct = sum(s.get('correct',0) for s in sessions)

    return {
        'ok': True,
        'sessions': sessions[-10:],
        'total_sessions': len(sessions),
        'avg_duration': total_duration / max(1, len(sessions)),
        'avg_accuracy': total_correct / max(1, total_q),
        'trend': sessions[-14:],
    }

# ================================================================
# 测试与验证
# ================================================================

def run_self_test():
    """模块自检"""
    results = []
    # IRT
    try:
        p = irt_probability(0.0, 1.0, 0.0)
        assert 0.4 < p < 0.6
        theta = irt_update_theta(0.0, 1.0, 0.0, True)
        assert theta > 0
        results.append(('IRT', True, f'p={p:.2f} theta->{theta:.2f}'))
    except Exception as e:
        results.append(('IRT', False, str(e)))

    # BKT
    try:
        pm = bkt_update(0.3, True)
        assert pm > 0.3
        results.append(('BKT', True, f'0.3-> {pm:.2f}'))
    except Exception as e:
        results.append(('BKT', False, str(e)))

    # ZPD
    try:
        z = calculate_zpd()
        assert 'optimal' in z
        results.append(('ZPD', True, f"optimal={z['optimal']:.2f}"))
    except Exception as e:
        results.append(('ZPD', False, str(e)))

    # 认知负荷
    try:
        cl = calculate_total_load("私は学生です。", "N5")
        assert 'total' in cl
        results.append(('CognitiveLoad', True, f"total={cl['total']}"))
    except Exception as e:
        results.append(('CognitiveLoad', False, str(e)))

    # 布鲁姆
    try:
        b = classify_bloom_level({'name': '〜ので（原因）', 'level': 'N4', 'options': ['ので','から']})
        results.append(('Bloom', True, f'level={b}'))
    except Exception as e:
        results.append(('Bloom', False, str(e)))

    # 支架
    try:
        s = recommend_scaffold_level(p_mastery=0.2)
        assert s == 'full'
        results.append(('Scaffold', True, f'0.2->{s}'))
    except Exception as e:
        results.append(('Scaffold', False, str(e)))

    # 整体
    try:
        analytics = get_learning_analytics()
        assert 'profile' in analytics
        results.append(('Analytics', True, f"theta={analytics['profile']['overall_ability']:.2f}"))
    except Exception as e:
        results.append(('Analytics', False, str(e)))

    return results

if __name__ == '__main__':
    for name, ok, msg in run_self_test():
        print(f"{'✅' if ok else '❌'} {name}: {msg}")
