# -*- coding: utf-8 -*-
"""
完整教育心理学模块测试 - v16
覆盖所有教育心理学功能：IRT, BKT, ZPD, 认知负荷, 布鲁姆, 支架, 元认知, 错误分析, 动机, 学习分析
"""
import sys
import json
import math

def test_irt():
    import edu_psychology as ep
    print("== IRT 能力估计 ==")
    # P(theta=b) = 0.5
    p = ep.irt_probability(0.0, 1.0, 0.0)
    assert abs(p - 0.5) < 0.01, f"IRT P(0,0) should be 0.5, got {p}"
    # 能力越高，正确概率越高
    p_low = ep.irt_probability(-1.0, 1.0, 0.0)
    p_high = ep.irt_probability(1.0, 1.0, 0.0)
    assert p_low < p_high, "IRT monotonic"
    # 更新：答对能力上升
    th = ep.irt_update_theta(0.0, 1.0, 0.0, True)
    assert th > 0, f"Correct should increase theta, got {th}"
    th2 = ep.irt_update_theta(0.0, 1.0, 0.0, False)
    assert th2 < 0, f"Wrong should decrease theta, got {th2}"
    # 边界
    th_max = ep.irt_update_theta(3.0, 1.0, -3.0, True)
    assert th_max <= ep.IRT_THETA_MAX
    print("✅ IRT 通过")

def test_bkt():
    import edu_psychology as ep
    print("== BKT 知识追踪 ==")
    # 答对掌握度上升
    pm = ep.bkt_update(0.3, True)
    assert pm > 0.3, f"BKT correct should increase, 0.3->{pm}"
    # 答错可能下降或微升（取决于参数），但应合理
    pm2 = ep.bkt_update(0.8, False)
    # 高掌握答错后会下降
    assert pm2 < 0.8, f"High mastery wrong should decrease, 0.8->{pm2}"
    # 更新KC
    entry = ep.update_knowledge_component("test_grammar_〜ので", True, skill='grammar')
    assert entry['p_mastery'] > 0.1
    assert entry['attempts'] >= 1
    # 再次更新
    entry2 = ep.update_knowledge_component("test_grammar_〜ので", False, skill='grammar')
    assert entry2['attempts'] == entry['attempts'] + 1 or entry2['attempts'] >= 2
    print("✅ BKT 通过")

def test_zpd():
    import edu_psychology as ep
    print("== ZPD 最近发展区 ==")
    model = ep._load_learner_model()
    zpd = ep.calculate_zpd(model)
    assert 'current' in zpd and 'zpd_min' in zpd and 'zpd_max' in zpd
    assert zpd['zpd_min'] < zpd['zpd_max']
    assert zpd['current'] < zpd['optimal'] <= zpd['zpd_max']
    # 判断是否在ZPD
    assert ep.is_in_zpd(zpd['current'] + 0.5, zpd['current']) == True
    assert ep.is_in_zpd(zpd['current'] + 2.0, zpd['current']) == False
    rec = ep.recommend_zpd_difficulty(0.0)
    assert -3 <= rec <= 3
    print("✅ ZPD 通过")

def test_cognitive_load():
    import edu_psychology as ep
    print("== 认知负荷理论 ==")
    # 简单句负荷低
    cl_simple = ep.calculate_total_load("私は学生です。", "N5")
    cl_complex = ep.calculate_total_load("若い棋士が多少、尊大な感じになるのはよくあることで、そういうことは将棋界に限った話ではないでしょう。", "N2")
    assert cl_simple['total'] < cl_complex['total'], f"Simple {cl_simple['total']} should < complex {cl_complex['total']}"
    assert cl_simple['intrinsic'] < cl_complex['intrinsic']
    # 总负荷结构
    assert 'intrinsic' in cl_simple and 'extraneous' in cl_simple and 'germane' in cl_simple
    assert 0 <= cl_simple['total'] <= 1
    # 调整
    qs = [{'text': '私は学生です。', 'level': 'N5'}, {'text': cl_complex['intrinsic'], 'level': 'N2', 'text': "このように、色は人々にいろいろな感じを与え、生活に役立っているのです。"}]
    # 用真实文本
    qs = [{'text': '私は学生です。', 'level': 'N5'}, {'text': 'このように、色は人々にいろいろな感じを与え、生活に役立っているのです。', 'level': 'N3'}, {'text': '若い棋士が多少、尊大な感じになるのはよくあることで、そういうことは将棋界に限った話ではないでしょう。', 'level': 'N2'}]
    adjusted = ep.adjust_for_cognitive_load(qs, capacity=0.75)
    assert len(adjusted) == len(qs)
    print("✅ 认知负荷 通过")

def test_bloom():
    import edu_psychology as ep
    print("== 布鲁姆分类法 ==")
    q1 = {'name': '〜ではない', 'level': 'N5', 'options': ['ではない','です']}
    b1 = ep.classify_bloom_level(q1)
    assert b1 in ep.BLOOM_LEVELS
    q2 = {'name': '〜のに（逆接）', 'level': 'N3', 'options': ['のに','ので','から','けど']}
    b2 = ep.classify_bloom_level(q2)
    assert b2 in ep.BLOOM_LEVELS
    coverage = ep.ensure_bloom_coverage([q1, q2, {'name':'test','level':'N4','options':['a','b','c','d']}])
    assert 'counts' in coverage and 'coverage' in coverage
    print("✅ 布鲁姆 通过")

def test_scaffold():
    import edu_psychology as ep
    print("== 支架式教学 ==")
    assert ep.recommend_scaffold_level(p_mastery=0.2) == 'full'
    assert ep.recommend_scaffold_level(p_mastery=0.4) == 'high'
    assert ep.recommend_scaffold_level(p_mastery=0.6) == 'medium'
    assert ep.recommend_scaffold_level(p_mastery=0.8) == 'low'
    assert ep.recommend_scaffold_level(p_mastery=0.95) == 'none'
    # 渐退
    hist = [{'correct': True, 'scaffold': 'full'}, {'correct': True, 'scaffold': 'full'}, {'correct': True, 'scaffold': 'full'}, {'correct': True, 'scaffold': 'full'}, {'correct': True, 'scaffold': 'full'}]
    faded = ep.fade_scaffold(hist)
    # 连续正确应提升（减少支架）
    assert ep.SCAFFOLD_LEVELS[faded]['order'] > ep.SCAFFOLD_LEVELS['full']['order']
    print("✅ 支架 通过")

def test_metacog():
    import edu_psychology as ep
    print("== 元认知 ==")
    res = ep.record_confidence("test_kc", 0.8, True)
    assert 'calibration' in res
    assert res['calibration'] > 0.7  # 高信心答对校准高
    res2 = ep.record_confidence("test_kc", 0.9, False)
    assert res2['overconfident'] == True
    res3 = ep.record_confidence("test_kc", 0.2, True)
    assert res3['underconfident'] == True
    prompt = ep.metacognitive_prompt()
    assert isinstance(prompt, str) and len(prompt) > 5
    print("✅ 元认知 通过")

def test_error_analysis():
    import edu_psychology as ep
    print("== 错误分析 ==")
    q = {'name': '〜ので', 'text': '雨が降ったので、出かけませんでした。'}
    err = ep.analyze_error(q, 'から', 'ので')
    assert err in ep.ERROR_TAXONOMY or err is None or isinstance(err, str)
    # 记录
    ep.record_error('grammar_confusion', '〜ので')
    rem = ep.get_error_remediation('grammar_confusion')
    assert 'strategy' in rem and 'suggestion' in rem
    print("✅ 错误分析 通过")

def test_motivation_flow():
    import edu_psychology as ep
    print("== 动机与心流 ==")
    flow = ep.estimate_flow_state()
    assert flow['state'] in ('flow','anxiety','boredom','control')
    assert 'challenge' in flow and 'skill' in flow
    ep.update_motivation(True)
    ep.update_motivation(False)
    fb = ep.recommend_motivational_feedback(True, streak=5)
    assert 'message' in fb
    fb2 = ep.recommend_motivational_feedback(False, error_type='particle_error')
    assert 'message' in fb2
    print("✅ 动机心流 通过")

def test_learning_analytics():
    import edu_psychology as ep
    print("== 学习分析仪表盘 ==")
    analytics = ep.get_learning_analytics(days=7)
    assert 'profile' in analytics
    assert 'srs' in analytics
    assert 'cloze' in analytics
    assert 'mastery_distribution' in analytics
    assert 'forgetting_curve' in analytics
    assert 'recommendations' in analytics
    assert len(analytics['forgetting_curve']) > 0
    # 推荐
    recs = ep.generate_recommendations(ep._load_learner_model(), analytics['profile'])
    assert isinstance(recs, list)
    print("✅ 学习分析 通过")

def test_adaptive_quiz():
    import edu_psychology as ep
    print("== 自适应出题整合 ==")
    base = ep.recommend_quiz_config_psy()
    assert base['ok']
    assert 'psy' in base
    assert 'theta' in base['psy']
    assert 'zpd' in base['psy']
    assert 'flow' in base['psy']
    # 自适应多源出题
    result = ep.adaptive_cloze_multi(total=5)
    assert result['ok']
    assert len(result['questions']) <= 5
    if result['questions']:
        q = result['questions'][0]
        assert 'scaffold' in q
        assert 'bloom' in q
        assert 'cognitive_load' in q
        assert 'in_zpd' in q
    print("✅ 自适应出题 通过")

def test_srl():
    import edu_psychology as ep
    print("== 自我调节学习 ==")
    plan = ep.get_study_plan_srl()
    # 可能没有书，允许ok False
    if plan.get('ok') == False:
        print("⚠️ 无书，跳过SRL计划详细检查")
    else:
        assert 'srl' in plan
        assert 'forethought' in plan['srl']
    # 会话记录
    res = ep.record_study_session({'duration': 300, 'questions': ['q1','q2'], 'correct': 1})
    assert res['ok']
    analytics = ep.get_session_analytics()
    assert analytics['ok']
    print("✅ SRL 通过")

def test_integration_with_textbook():
    import textbook, edu_psychology as ep
    print("== 与课本模块整合 ==")
    # 原有推荐仍工作
    rec = textbook.recommend_quiz_config()
    assert rec['ok']
    # 多源出题仍工作
    multi = textbook.make_cloze_multi(total=3)
    assert multi['ok']
    # 心理学增强版
    psy_rec = ep.recommend_quiz_config_psy()
    assert psy_rec['ok']
    psy_multi = ep.adaptive_cloze_multi(total=3)
    assert psy_multi['ok']
    print("✅ 整合 通过")

def test_self_test():
    import edu_psychology as ep
    print("== 模块自检 ==")
    results = ep.run_self_test()
    for name, ok, msg in results:
        status = "✅" if ok else "❌"
        print(f"{status} {name}: {msg}")
        assert ok, f"{name} failed: {msg}"
    print("✅ 自检 通过")

if __name__ == '__main__':
    tests = [
        test_irt,
        test_bkt,
        test_zpd,
        test_cognitive_load,
        test_bloom,
        test_scaffold,
        test_metacog,
        test_error_analysis,
        test_motivation_flow,
        test_learning_analytics,
        test_adaptive_quiz,
        test_srl,
        test_integration_with_textbook,
        test_self_test,
    ]
    failed = []
    for t in tests:
        try:
            t()
        except Exception as e:
            import traceback
            print(f"❌ {t.__name__} 失败: {e}")
            traceback.print_exc()
            failed.append(t.__name__)
    if failed:
        print(f"\n===== 测试失败 {len(failed)}/{len(tests)}: {', '.join(failed)} =====")
        sys.exit(1)
    else:
        print(f"\n===== 全部 {len(tests)} 项教育心理学测试通过 =====")
        sys.exit(0)
