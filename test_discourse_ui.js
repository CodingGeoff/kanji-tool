/* 篇章精读 前端逻辑冒烟测试（无浏览器环境，用最小 DOM 桩在 Node 里跑真实代码）
 * 目的：语法检查抓不到的运行时错误 —— 未定义函数、空引用、渲染分支写错、
 *       以及「答案不下发」这条反作弊契约在真实渲染路径上是否成立。
 * 运行：node test_discourse_ui.js
 */
const fs = require('fs');
const src = fs.readFileSync('static/index.html', 'utf8');
let script = src.split('<script>').pop().split('</script>')[0];
// eval 里的 let/const 不会变成全局，测试需要读写模块级状态 → 仅测试期改成 var
script = script.replace(/\blet dcQuiz=null;/, 'var dcQuiz=null;')
               .replace(/\blet dcPv=null;/, 'var dcPv=null;')
               .replace(/\blet dcBusy=false,dcSeq=0;/, 'var dcBusy=false,dcSeq=0;');

let FAILS = [];
const check = (c, m) => { if (!c) { FAILS.push(m); console.log('  FAIL:', m); } };

/* ---------- 最小 DOM 桩 ---------- */
class El {
  constructor(id = '') {
    this.id = id; this._html = ''; this.style = {}; this.dataset = {};
    this.children = []; this.value = ''; this.textContent = ''; this.disabled = false;
    this._cls = new Set();
    this.classList = {
      add: (...c) => c.forEach(x => this._cls.add(x)),
      remove: (...c) => c.forEach(x => this._cls.delete(x)),
      toggle: (c, on) => { on === undefined ? (this._cls.has(c) ? this._cls.delete(c) : this._cls.add(c)) : (on ? this._cls.add(c) : this._cls.delete(c)); },
      contains: c => this._cls.has(c),
    };
  }
  get innerHTML() { return this._html; }
  set innerHTML(v) { this._html = String(v); }
  addEventListener() {} removeEventListener() {}
  appendChild(c) { this.children.push(c); return c; }
  scrollIntoView() {} focus() { this.focused = true; } click() {}
  querySelector() { return null; } querySelectorAll() { return []; }
  getBoundingClientRect() { return { top: 0, left: 0, width: 800, height: 600 }; }
  closest() { return null; } setAttribute() {} getAttribute() { return null; } remove() {}
}
const registry = new Map();
const el = id => { if (!registry.has(id)) registry.set(id, new El(id)); return registry.get(id); };

global.document = {
  body: new El('body'), documentElement: new El('html'),
  querySelector: s => (s.startsWith('#') ? el(s.slice(1)) : new El(s)),
  querySelectorAll: () => [],
  getElementById: id => (registry.has(id) ? registry.get(id) : null),
  createElement: () => new El(), addEventListener: () => {},
  createTextNode: () => new El(), cookie: '',
};
global.window = {
  matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
  scrollTo() {}, addEventListener() {}, location: { href: '', search: '', hash: '' },
  localStorage: null, setTimeout, clearTimeout, speechSynthesis: null, innerWidth: 1400,
};
global.navigator = { userAgent: 'node', language: 'zh-CN', clipboard: { writeText: async () => {} } };
global.localStorage = {
  _d: {}, getItem(k) { return this._d[k] ?? null; }, setItem(k, v) { this._d[k] = String(v); },
  removeItem(k) { delete this._d[k]; },
};
global.window.localStorage = global.localStorage;
global.Audio = function () { return { play() {}, pause() {}, addEventListener() {} }; };
global.matchMedia = global.window.matchMedia;
global.requestAnimationFrame = fn => setTimeout(fn, 0);
global.alert = () => {}; global.confirm = () => true;
// 页面初始化会并发拉一堆与本测试无关的接口，失败了不影响被测逻辑
process.on('unhandledRejection', (e) => { if (process.env.UIDEBUG) console.log('REJ:', e && (e.stack || e.message)); });

/* ---------- 假后端 ---------- */
const PASSAGE = {
  id: 7, title: 'クマ捕獲の現場で何が',
  sentences: [
    { idx: 0, kind: 'heading', text: '生きた心地がしなかった クマ捕獲の現場で何が' },
    { idx: 1, kind: 'caption', text: 'クマ被害' },
    { idx: 2, kind: 'body', text: 'ことし6月、福島市で1人のハンターがクマと対じした。' },
    { idx: 3, kind: 'body', text: 'クマは路上で4人を襲い、とどまっていた。' },
    { idx: 4, kind: 'heading', text: 'ハンター「あのようなクマは初めて」' },
    { idx: 5, kind: 'body', text: '市は緊急銃猟を実施することを決断した。' },
  ],
};
const QUIZ = {
  ok: true, quiz_id: 'q-1', title: PASSAGE.title, n_fresh: 3, n_input: 1,
  difficulty_mix: { hard: 2, medium: 1 },
  questions: [
    { qid: '7-0', qtype: 'particle', type_label: '格助词还原', difficulty: 'medium',
      text_policy: 'closed', answer_format: 'choice', prompt: '空欄に入る助詞を選べ',
      context: 'クマは路上で4人（＿）襲い、とどまっていた。', options: ['が', 'を', 'に', 'から'], sent_idx: 1 },
    { qid: '7-1', qtype: 'compare', type_label: '数值比较', difficulty: 'hard',
      text_policy: 'open', answer_format: 'choice', prompt: '最も大きい数値は',
      context: '（本文全体を参照）', options: ['81件', '54件', '4人', '1人'], sent_idx: 0 },
    { qid: '7-2', qtype: 'connective', type_label: '接续词还原', difficulty: 'hard',
      text_policy: 'closed', answer_format: 'input', hint: '3 文字', prompt: '空欄に入る接続詞',
      context: '＿＿、市は緊急銃猟を実施することを決断した。', options: [], sent_idx: 2 },
  ],
};
const GRADE = { ok: true, correct: true, answer: 'を', objectivity: 'verbatim',
  evidence: ['答案「4人を」为原文原样'], explain: '格助词题' };
const FURI = { ok: true, rows: PASSAGE.sentences.map(s => ({ idx: s.idx, kind: s.kind,
  tokens: [{ s: s.text.slice(0, 2), r: 'よみ' }, { s: s.text.slice(2) }] })) };
const calls = [];
global.fetch = async (url, opt) => {
  calls.push({ url, body: opt && opt.body });
  const j = d => ({ json: async () => d, ok: true, status: 200, text: async () => JSON.stringify(d) });
  if (url.includes('/api/discourse/quiz')) return j(QUIZ);
  if (url.includes('/furigana')) return j(FURI);
  if (url.includes('/capacities')) return j({ ok: true, capacities: { 7: { stems: 119, deliveries: 207, variants: 1451298, fresh: 100, done: 19 } } });
  if (url.includes('/capacity')) return j({ ok: true, capacity: { stems: 119, deliveries: 207, variants: 1451298, fresh: 100, done: 19 } });
  if (url.includes('/api/discourse/grade')) return j(GRADE);
  if (/\/api\/discourse\/passages\/\d+$/.test(url)) return j({ ok: true, passage: PASSAGE, preview: {} });
  if (url.includes('/api/discourse/passages')) return j({ ok: true, passages: [{ id: 7, title: PASSAGE.title, n_para: 3, n_sent: 3, n_char: 120 }] });
  if (url.includes('/api/discourse/stats')) return j({ ok: true, stats: { total: 0 } });
  if (url.includes('/api/stats')) return j({ srs: { due: 0, total: 0 }, sentences: 0, kanji: 0, learned: 0 });
  if (url.includes('/api/review/due')) return j({ items: [], due: 0 });
  if (url.includes('/api/discourse/answer')) return j({ ok: true, saved: 3 });
  return j({ ok: true });
};

/* ---------- 载入页面脚本 ---------- */
try { eval(script); } catch (e) { console.log('脚本加载异常（忽略初始化副作用）:', e.message); }

(async () => {
  try {
  console.log('\n[UI-1] 进入答题：外壳 + 双栏 + 阅读面板');
  await dcStart(7, 3);
  const shell = el('dcQuizView').innerHTML;
  check(shell.includes('dc-split'), '缺少双栏容器 dc-split');
  check(shell.includes('dc-rcol') && shell.includes('dc-reader'), '缺少阅读面板');
  check(shell.includes('dc-fab'), '缺少移动端悬浮按钮');
  check(shell.includes('ふりがな') && shell.includes('A−') && shell.includes('A＋'), '阅读面板缺少注音/字号控件');

  console.log('[UI-2] 原文渲染：小标题 / 图注 / 正文分别渲染，正文带定位锚点');
  const reader = dcReaderHTML();      // 桩 DOM 不解析 HTML，直接验渲染函数的输出
  check(reader.includes('<h4>') && reader.includes('クマ捕獲の現場'), '小标题没有渲染成标题样式');
  check(reader.includes('class="cap"') && reader.includes('クマ被害'), '图注/栏目标签没有单独样式');
  check((reader.match(/class="dc-s"/g) || []).length === 3, '正文句锚点数量不对（应为 3）');
  check(reader.includes('id="dcS0"') && reader.includes('id="dcS2"'), '正文句缺少 dcS 锚点 id');
  check(!reader.includes('id="dcS3"'), '锚点编号把小标题也算进去了（跳转会跳错行）');

  console.log('[UI-3] 闭卷题：答案与解析不在页面里');
  let qhtml = el('dcQcol').innerHTML;
  check(qhtml.includes('闭卷'), '闭卷题没有标注');
  check(qhtml.includes('4人（＿）襲い'), '题面上下文没渲染');
  check(!qhtml.includes('答案「4人を」'), '未作答就把判定依据渲染出来了（泄题）');
  check(!/正解：/.test(qhtml), '未作答就显示了正解');

  console.log('[UI-4] 作答 → 服务端判分 → 解析与「跳到出处」');
  dcPick(1);
  await dcCheck();
  const exp = el('dcExp').innerHTML;
  check(exp.includes('正解：'), '判分后没有显示正解');
  check(exp.includes('答案「4人を」为原文原样'), '判分后没有显示判定依据');
  check(exp.includes('dcJump(1)'), '缺少「跳到原文出处」按钮');
  check(calls.some(c => c.url.includes('/api/discourse/grade')), '没有调用服务端判分接口');
  const gradeCall = calls.filter(c => c.url.includes('/grade')).pop();
  check(/"response":"1"/.test(gradeCall.body), '判分请求没有带上所选项下标');

  console.log('[UI-5] 跳转定位：打开面板并高亮对应句');
  dcJump(1);
  await new Promise(r => setTimeout(r, 120));
  check(el('dcRcol')._cls.has('open') || el('dcRcol').style.display === 'flex', '跳转没有打开阅读面板');

  console.log('[UI-6] 开卷题：原文默认展开，不记为「参考原文」');
  dcNext();
  const q2 = el('dcQcol').innerHTML;
  check(q2.includes('开卷·扫读'), '开卷题没有标注');
  check(q2.includes('📄 打开原文'), '开卷题应直接提供打开原文');
  check(dcQuiz.peeked === false, '开卷题不应预置 peeked');
  dcPick(0); await dcCheck();
  check(dcQuiz.ans[1].peeked === false, '开卷题被错误记成「参考原文」');
  check(dcQuiz.ok === 2, '开卷题答对没有计分');

  console.log('[UI-7] 填空题：无选项、有输入框、服务端判分');
  dcNext();
  const q3 = el('dcQcol').innerHTML;
  check(q3.includes('id="dcInput"'), '填空题没有输入框');
  check(!q3.includes('sb-tile'), '填空题不应有选项按钮');
  check(q3.includes('3 文字'), '填空题没有给出字数提示');
  el('dcInput').value = 'しかし';
  await dcCheck();
  check(calls.filter(c => c.url.includes('/grade')).length === 3, '填空题没有走服务端判分');

  console.log('[UI-8] 偷看原文：闭卷题记账为「参考原文」，不计入闭卷分');
  await dcStart(7, 3);
  const before = dcQuiz.ok;
  dcPeek();
  check(dcQuiz.peeked === true, 'dcPeek 未生效');
  dcPick(1); await dcCheck();
  check(dcQuiz.ans[0].peeked === true, '偷看后没有记为参考原文');
  check(dcQuiz.ok === before, '偷看后答对仍计入闭卷分（反作弊失效）');

  console.log('[UI-9] 注音开关 / 字号 / 抽屉开合');
  await dcToggleFuri();
  check(dcQuiz.furiOn === true && el('dcReader').innerHTML.includes('<ruby'), '注音开关没有渲染 ruby');
  await dcToggleFuri();
  check(dcQuiz.furiOn === false && !el('dcReader').innerHTML.includes('<ruby'), '注音关不掉');
  const f1 = dcFontSize(1), f2 = dcFontSize(-1);
  check(f1 === f2 + 1 && localStorage.getItem('dcFont'), '字号调节/持久化失效');
  dcCloseReader();
  check(dcQuiz.readerOpen === false, '阅读面板关不掉');
  dcOpenReader(true);
  check(dcQuiz.readerOpen === true, '阅读面板打不开');

  console.log('[UI-10] 移动端：抽屉模式下也能开合，FAB 文案随状态变化');
  global.window.matchMedia = () => ({ matches: true, addEventListener() {}, addListener() {} });
  global.matchMedia = global.window.matchMedia;
  dcRender();
  check(dcMobile() === true, '移动端断点判定失效');
  dcCloseReader(); dcSyncFab();
  const fabClosed = el('dcFab').textContent;
  dcFabTap();
  const fabOpen = el('dcFab').textContent;
  check(fabClosed !== fabOpen && /原文/.test(fabClosed) && /收起/.test(fabOpen),
    `FAB 文案未随状态变化（${fabClosed} → ${fabOpen}）`);
  check(el('dcRcol')._cls.has('open'), '移动端抽屉没有打开');

  console.log('[UI-11] 连点防抖：组卷进行中再点直接忽略，不叠出第二套题');
  calls.length = 0;
  const s1 = dcStart(7, 3);                 // 不 await 第一笔，立刻再点一次
  const s2 = dcStart(7, 3);
  await Promise.all([s1, s2]);
  check(calls.filter(c => c.url.includes('/api/discourse/quiz')).length === 1,
    '连点仍然发出了多次组卷请求（就是「闪过一大堆题目」的根源）');
  check(dcBusy === false, '忙碌标记没有复位（会卡死后续操作）');

  console.log('[UI-12] 列表加载：题量统计走批量接口，一次请求全拿');
  calls.length = 0;
  await dcLoad();
  await new Promise(r => setTimeout(r, 30));
  check(calls.some(c => c.url.includes('/api/discourse/passages/capacities')),
    '没有调用批量题量接口');
  check(el('dcCap7').innerHTML.includes('题干 <b>119</b>'), '题量统计没有填进列表');
  check(!calls.some(c => c.url.endsWith('/capacity')), '还在按篇逐个请求题量');

  } catch (e) { console.log('运行时异常:', e && e.stack || e); FAILS.push('运行时异常: ' + (e && e.message)); }
  console.log('\n' + '='.repeat(56));
  if (FAILS.length) { console.log(`FAILED: ${FAILS.length} 项`); FAILS.forEach(f => console.log(' -', f)); process.exit(1); }
  console.log('UI ALL PASSED（12 组前端行为断言）');
})();
