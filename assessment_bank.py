# -*- coding: utf-8 -*-
"""人工题库层：多题共用篇章、来源溯源、审核状态与结构化质量门禁。

SEED_PASSAGES 为项目原创初稿，不冒充官方真题；默认 status=draft，只能用于
试测。只有教师在独立复核后批准为 approved，才应进入正式组卷。
"""
import copy
import json
import random
import time
import db

_REVIEW_KEY = 'assessment_passage_reviews_v1'

SEED_PASSAGES = [
 {'id':'orig-n3-library-001','level':'N3','genre':'通知','domain':'生活','status':'draft',
  'source':{'kind':'project_original','title':'図書館の臨時利用案内','author':'kanji-tool assessment team','url':None,'license':'repository-original','adapted':False},
  'text':'市立図書館では、館内の空調設備を取り替えるため、六月十日から十四日まで二階の閲覧室を閉鎖します。一階の新聞・雑誌コーナーと児童室は通常どおり利用できます。ただし、工事中は大きな音が出る時間がありますので、静かな場所で勉強したい方は、駅前分館をご利用ください。二階にある本を借りたい場合は、前日までにウェブサイトから予約してください。職員が一階の受付に用意します。返却ポストは工事中も二十四時間利用できます。',
  'items':[
   {'id':'q1','process':'retrieve','evidence':['p1:s1','p1:s2'],'prompt':'六月十二日に利用できない場所はどこですか。','options':['二階の閲覧室','一階の新聞・雑誌コーナー','児童室','返却ポスト'],'answer':0,'rationale':'閉鎖期間は六月十日から十四日までで、対象は二階の閲覧室。'},
   {'id':'q2','process':'apply_condition','evidence':['p1:s4','p1:s5'],'prompt':'六月十一日に二階の本を借りたい人は、どうすればいいですか。','options':['当日、二階へ取りに行く','前日までにウェブで予約する','駅前分館へ返却する','工事が終わるまで待つ'],'answer':1,'rationale':'予約すれば職員が一階受付に用意する。'},
   {'id':'q3','process':'infer','evidence':['p1:s3'],'prompt':'駅前分館の利用を勧めている主な理由は何ですか。','options':['本館では本を借りられないから','児童室が混雑するから','工事の音を避けられるから','返却ポストが使えないから'],'answer':2,'rationale':'工事中に大きな音が出るため、静かに勉強したい人へ勧めている。'}]},
 {'id':'orig-n2-remote-001','level':'N2','genre':'意見文','domain':'職場','status':'draft',
  'source':{'kind':'project_original','title':'出社日を一律に決めるべきか','author':'kanji-tool assessment team','url':None,'license':'repository-original','adapted':False},
  'text':'在宅勤務を続ける企業の中には、社員同士の交流を増やすため、全員が同じ曜日に出社する制度を導入するところがある。確かに、相談相手がその場にいれば、短い会話から問題が解決することもある。しかし、一律の出社日は、必ずしも交流を生むとは限らない。会議が一日中続けば、同じ建物にいても話す機会は増えないからだ。また、遠方に住む社員や育児中の社員にだけ大きな負担を求めることにもなりかねない。重要なのは出社回数ではなく、共同作業が必要な目的を先に定め、その目的に合う人が集まることである。制度の利用状況を定期的に確認し、参加しにくい人の意見に応じて運用を変える仕組みも欠かせない。',
  'items':[
   {'id':'q1','process':'main_idea','evidence':['p1:s3','p1:s6'],'prompt':'筆者の主張に最も近いものはどれですか。','options':['在宅勤務は社員の交流を完全に失わせる','全員の出社曜日を同じにすれば問題は解決する','目的に応じて集まる人を決め、運用を見直すべきだ','遠方に住む社員は出社制度の対象外にすべきだ'],'answer':2,'rationale':'回数や一律指定より目的適合と継続的見直しを重視している。'},
   {'id':'q2','process':'argument_role','evidence':['p1:s2'],'prompt':'「短い会話から問題が解決することもある」と述べた役割は何ですか。','options':['反対意見の利点を一度認める','筆者の最終結論を示す','育児中社員の例を否定する','制度の調査結果を引用する'],'answer':0,'rationale':'「確かに」で利点を認めた後、「しかし」で限定している。'},
   {'id':'q3','process':'infer','evidence':['p1:s3','p1:s4'],'prompt':'本文から推測できることはどれですか。','options':['同じ場所にいることだけでは交流は保証されない','会議を増やせば負担の差はなくなる','出社回数が多いほど共同作業は成功する','在宅勤務では相談が一切できない'],'answer':0,'rationale':'同じ建物でも会議が続けば話す機会は増えないという例が根拠。'}]},
 {'id':'orig-n1-ai-001','level':'N1','genre':'比較読解','domain':'教育','status':'draft',
  'source':{'kind':'project_original','title':'作文指導における生成AI（対照資料）','author':'kanji-tool assessment team','url':None,'license':'repository-original','adapted':False},
  'texts':[{'label':'資料A','text':'生成AIの利用を一律に禁じても、学習者が教室外で使う可能性は残る。それなら、出力の根拠を確かめ、自分の意図に合わせて修正する過程を授業で扱う方がよい。評価も完成した文章だけでなく、下書き、修正理由、参照資料を含めて行えば、思考の過程を確認できる。問題はAIを使ったか否かではなく、書き手が最終的な表現に責任を持てるかである。'},
           {'label':'資料B','text':'作文の初期段階で生成AIに頼ると、学習者自身が言いたい内容を探し、適切な構成を試す機会が減る。出力を批判的に読む活動には意味があるが、それには一定の言語力と分野知識が要る。したがって、いつでも自由に使わせるのではなく、まず自力で草稿を書かせた上で、比較や推敲の材料として限定的に用いるべきだ。'}],
  'items':[
   {'id':'q1','process':'integrate_commonality','evidence':['A:s2','B:s2'],'prompt':'両方の資料に共通する考えはどれですか。','options':['生成AIを作文授業から完全に排除するべきだ','AIの出力を検討・修正する活動には教育的意味がある','完成した文章だけで評価するべきだ','初級者ほど自由にAIを使うべきだ'],'answer':1,'rationale':'Aは検証と修正、Bも批判的に読む活動の意味を認める。'},
   {'id':'q2','process':'integrate_difference','evidence':['A:s1','B:s3'],'prompt':'二つの資料の最も大きな違いは何ですか。','options':['作文教育が必要かどうか','AIが誤情報を出すかどうか','AIを使う時期と条件をどの程度制限するか','参照資料を示す必要があるか'],'answer':2,'rationale':'Aは授業内で過程を扱う方向、Bは自力草稿後の限定利用を要求する。'},
   {'id':'q3','process':'evaluate_claim','evidence':['A:s3','B:s2'],'prompt':'両者が特に重視している能力の組み合わせとして適切なものはどれですか。','options':['入力速度と暗記量','責任ある修正と批判的判断','敬語知識と発音','翻訳速度と文字数'],'answer':1,'rationale':'Aは最終表現への責任、Bは批判的読解に必要な能力を中心にする。'}]}
]


def _reviews():
    try:return json.loads(db.get_setting(_REVIEW_KEY,'{}') or '{}')
    except Exception:return {}


def effective_status(p):
    rev=_reviews().get(p['id'],{})
    return rev.get('status',p.get('status','draft'))


def validate_passage(p):
    issues=[]
    if not p.get('id') or not p.get('level') or not p.get('genre'):issues.append('missing_metadata')
    src=p.get('source') or {}
    for k in ('kind','title','author','license'):
        if not src.get(k):issues.append('source_'+k+'_missing')
    material=p.get('text') or ''.join(x.get('text','') for x in p.get('texts',[]))
    if len(material)<80:issues.append('passage_too_short')
    if len(p.get('items',[]))<2:issues.append('too_few_items')
    for q in p.get('items',[]):
        opts=q.get('options') or []; ans=q.get('answer')
        if len(opts)!=4 or len(set(opts))!=4:issues.append(q.get('id','?')+':options')
        if not isinstance(ans,int) or not 0<=ans<len(opts):issues.append(q.get('id','?')+':answer')
        if not q.get('rationale') or not q.get('evidence'):issues.append(q.get('id','?')+':evidence')
        if q.get('process') not in {'retrieve','apply_condition','infer','main_idea','argument_role','integrate_commonality','integrate_difference','evaluate_claim'}:
            issues.append(q.get('id','?')+':process')
    return issues


def list_passages(level=None,status=None):
    out=[]
    for p in SEED_PASSAGES:
        q=copy.deepcopy(p);q['effective_status']=effective_status(p);q['validation_issues']=validate_passage(p)
        if level and q['level']!=level:continue
        if status and q['effective_status']!=status:continue
        out.append(q)
    return out


def generate(level=None,status='approved',seed=None,include_answers=False):
    pool=[p for p in list_passages(level,status) if not p['validation_issues']]
    if not pool:return {'ok':False,'error':'没有符合等级和审核状态的篇章。原创种子题默认为 draft，须教师复核批准；试测可显式请求 status=draft。'}
    p=random.Random(seed if seed is not None else time.time_ns()).choice(pool)
    if not include_answers:
        for q in p['items']:
            q.pop('answer',None);q.pop('rationale',None)
    return {'ok':True,'passage':p,'use':'pilot' if p['effective_status']!='approved' else 'operational'}


def review(passage_id,status,reviewer,checklist,notes=''):
    if passage_id not in {p['id'] for p in SEED_PASSAGES}:return {'ok':False,'error':'unknown passage'}
    if status not in ('draft','reviewed','approved','retired'):return {'ok':False,'error':'invalid status'}
    required={'answer_unique','evidence_exact','level_fit','bias_checked','language_natural','source_checked'}
    checks={k:bool((checklist or {}).get(k)) for k in required}
    if status=='approved' and not all(checks.values()):return {'ok':False,'error':'批准前必须完成全部复核项','missing':[k for k,v in checks.items() if not v]}
    if not str(reviewer or '').strip():return {'ok':False,'error':'reviewer required'}
    rev=_reviews();rev[passage_id]={'status':status,'reviewer':str(reviewer)[:100],'checklist':checks,'notes':str(notes)[:1000],'timestamp':time.time()}
    db.set_setting(_REVIEW_KEY,json.dumps(rev,ensure_ascii=False));return {'ok':True,'review':rev[passage_id]}
