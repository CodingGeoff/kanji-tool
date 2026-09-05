# -*- coding: utf-8 -*-
"""分かち書き（意思群断句）金标准：全部来自真实歌词断句问题"""
import sys

sys.path.insert(0, '.')
import ktv

FAILS = []


def groups(ln):
    """与前端渲染一致：sp 边界 + 原文空格都是组界；纯英文组间的空格视为组内间隔。"""
    toks, _ = ktv.annotate_lyrics(ln)
    t = toks[0]
    out, cur = [], ''
    for x in t:
        s = x.get('s') or ''
        if x.get('sp'):
            if cur.strip():
                out.append(cur.strip())
            cur = ''
            if not s.strip():
                continue
        elif not s.strip():
            if cur.strip():
                out.append(cur.strip())
            cur = ''
            continue
        cur += s
    if cur.strip():
        out.append(cur.strip())
    # 前端 join(' ') 渲染：相邻纯英文组视觉上是一个段（I love you）
    merged = []
    for g in out:
        if merged and g and merged[-1] and g.isascii() and merged[-1].isascii():
            merged[-1] += ' ' + g
        else:
            merged.append(g)
    return merged


CASES = [
    # (原句, 期望分组) —— 全部来自《僕が死のうと思ったのは》等真实歌词的断句问题
    ('僕が 死のうと 思ったのは ウミネコが桟橋で鳴いたから',
     ['僕が', '死のうと', '思ったのは', 'ウミネコが', '桟橋で', '鳴いたから']),
    ('過去も啄ばんで飛んでいけ', ['過去も', '啄ばんで', '飛んでいけ']),   # 未知汉字啄ば+ん不拆
    ('誕生日に杏の花が咲いたから', ['誕生日に', '杏の', '花が', '咲いたから']),
    ('靴紐が解けたから', ['靴紐が', '解けたから']),                        # 解|けた 不拆
    ('結びなおすのは苦手なんだよ', ['結びなおすのは', '苦手なんだよ']),      # 复合动词不拆
    ('冷たい人と言われたから', ['冷たい', '人と', '言われたから']),          # 冷|たい 不拆
    ('あの日の僕にごめんなさいと', ['あの日の', '僕に', 'ごめんなさいと']),  # 連体詞合并/ごめんなさい
    ('心が空っぽになったから', ['心が', '空っぽに', 'なったから']),
    ('分かってる 分かってる けれど', ['分かってる', '分かってる', 'けれど']),  # 同词一致+空格
    ('少し好きになったよ', ['少し', '好きに', 'なったよ']),                  # 少|し好|き 不拆
    ('満たされたいと願うから', ['満たされたいと', '願うから']),
    ('錆びたアーチ橋', ['錆びた', 'アーチ橋']),                             # 錆|びた 不拆
    ('少年が僕を見つめていたから', ['少年が', '僕を', '見つめていたから']),  # 補助動詞いた跟随
    ('人の温もりを知ってしまったから', ['人の', '温もりを', '知ってしまったから']),  # しまった跟随
    ('立ち上がる', ['立ち上がる']),                                          # 复合动词
    ('夜空に瞬く星を見上げて', ['夜空に', '瞬く', '星を', '見上げて']),
    ('Forever 君に 会いたくて', ['Forever', '君に', '会いたくて']),          # 原文空格保留
    ('I love you 君を想う夜', ['I love you', '君を', '想う', '夜']),        # 英文段整段+回日文断开
    ('自転車で駅まで行く', ['自転車で', '駅まで', '行く']),
]


def run():
    n = 0
    for ln, exp in CASES:
        got = groups(ln)
        if got == exp:
            n += 1
        else:
            FAILS.append(f'{ln}\n    得到: {" | ".join(got)}\n    期望: {" | ".join(exp)}')
    # 自愈测试：旧版错位 sp 必须被清除重算
    toks, _ = ktv.annotate_lyrics('靴紐が解けたから')
    for t in toks[0]:
        t['sp'] = True                       # 模拟旧版全错标记
    ktv._seg_mark(toks[0], '靴紐が解けたから')
    sps = [t['s'] for t in toks[0] if t.get('sp')]
    if sps == ['解']:
        n += 1
    else:
        FAILS.append(f'自愈失败：错位 sp 清除重算后={sps}，期望 [解]')
    # 安全网测试：token 与原文不一致时必须放弃分词（全部清除且不新增）
    bad = [{'s': '完全无关的token串'}]
    ktv._seg_mark(bad, '靴紐が解けたから')
    if not any(t.get('sp') for t in bad):
        n += 1
    else:
        FAILS.append('安全网失败：不一致时仍打了 sp')
    print(f'===== 分かち書き金标准: 通过 {n} / {len(CASES) + 2} =====')
    for f in FAILS:
        print(' ', f)
    return len(FAILS)


if __name__ == '__main__':
    sys.exit(0 if run() == 0 else 1)
