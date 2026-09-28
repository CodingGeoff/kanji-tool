/* RAG 检索 前端行为冒烟测试（无浏览器，最小 DOM 桩 + 假后端，在 Node 里跑真实页面代码）
 * 针对用户实报的两个现象做回归：
 *   ①「检索失败：SyntaxError: Unexpected token '<', "<!DOCTYPE "... is not valid JSON」
 *      —— 后端返回 HTML 错误页时，界面必须给人话，而不是把浏览器的解析异常糊在脸上。
 *   ②「没有找到相关内容」但内容其实在
 *      —— 有命中就必须渲染；真没有时要说清是「索引没建好」还是「被自己的筛选挡了」。
 * 运行：node test_rag_ui.js
 */
const fs = require('fs');
const src = fs.readFileSync('static/index.html', 'utf8');
let script = src.split('<script>').pop().split('</script>')[0];
// eval 里的 let/const 不会进全局；测试要改写这些模块级状态
script = script.replace(/\blet ragBooks=\[\];/, 'var ragBooks=[];')
               .replace(/\blet ragSrcOrder=ragSrcLoad\(\);/, 'var ragSrcOrder=ragSrcLoad();')
               .replace(/\blet _ragSeq=0;/, 'var _ragSeq=0;');

let FAILS = [];
const check = (c, m) => { if (c) { console.log('  [OK]  ', m); } else { FAILS.push(m); console.log('  [FAIL]', m); } };

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
  scrollIntoView() {} focus() {} click() {}
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
process.on('unhandledRejection', e => { if (process.env.UIDEBUG) console.log('REJ:', e && (e.stack || e.message)); });

/* ---------- 假后端 ---------- */
const LINE = '寄り返す波が';
const row = (o) => Object.assign({
  type: 'lyric', channel: 'lyric', kind: 'line', id: 41, title: '打上花火',
  artist: '', text: LINE, score: 1.0, rank: 1.0, affinity: 1.0,
  tokens: [{ s: '寄', r: 'よ' }, { s: 'り返す', r: null }, { s: '波', r: 'なみ' }, { s: 'が', r: null }],
}, o || {});
const OK_BODY = {
  rows: [], lyrics: [row({ exact: true })], results: [row({ exact: true })],
  titles: {}, groups: { lyric: [row({ exact: true })], textbook: [], web: [] },
  meta: { terms: ['寄り返す', '波'], qvars: [], prior: ['lyric', 'textbook', 'web'],
    sort: 'priority', ms: 12, hits: { lyric: 1, textbook: 0, web: 0 },
    index: { ready: true, docs: 21000 } },
};
let MODE = 'ok';
global.fetch = async (url) => {
  const j = d => ({ ok: true, status: 200, json: async () => d, text: async () => JSON.stringify(d) });
  if (url.includes('/api/books')) return j({ rows: [] });
  if (!url.includes('/api/rag/search')) return j({ ok: true });
  if (MODE === 'ok') return j(OK_BODY);
  if (MODE === 'html500') return {            // Flask/网关的 HTML 错误页
    ok: false, status: 500,
    text: async () => '<!doctype html>\n<html lang=en>\n<title>500 Internal Server Error</title>\n',
    json: async () => { throw new SyntaxError("Unexpected token '<'"); },
  };
  if (MODE === 'json500') return {
    ok: false, status: 500,
    text: async () => JSON.stringify({ error: '服务器内部错误，请重试；若持续出现请把这条信息反馈给开发者', status: 500 }),
  };
  if (MODE === 'warming') return j({ rows: [], lyrics: [], results: [], titles: {},
    groups: { lyric: [], textbook: [], web: [] },
    meta: { terms: [], prior: ['lyric'], hits: {}, warming: true, index: { ready: false, docs: 0 } } });
  if (MODE === 'excluded') return j({ rows: [], lyrics: [], results: [], titles: {},
    groups: { lyric: [], textbook: [], web: [] },
    meta: { terms: [], prior: ['textbook'], hits: {}, index: { ready: true, docs: 21000 },
      excluded: { lyric: { hits: 1, sample: LINE, exact: true } } } });
  if (MODE === 'empty') return j({ rows: [], lyrics: [], results: [], titles: {},
    groups: { lyric: [], textbook: [], web: [] },
    meta: { terms: [], prior: ['lyric'], hits: {}, index: { ready: true, docs: 21000 } } });
  if (MODE === 'legacy') return j({          // 旧后端/部分失败：只有 lyrics，没有 results
    rows: [], lyrics: [row({})], titles: {}, meta: { terms: [], prior: ['lyric'], hits: {} } });
  return j(OK_BODY);
};

/* ---------- 载入页面脚本 ---------- */
try { eval(script); } catch (e) { console.log('脚本加载异常（忽略初始化副作用）:', e.message); }

const out = () => el('ragOut').innerHTML;

(async () => {
  try {
    el('ragQ').value = '寄り 返す 波が';
    el('ragLimit').value = '10';
    el('ragPerSong').value = '3';
    el('ragPerBook').value = '4';

    console.log('\n[UI-1] 正常命中：结果渲染出来，精确命中有徽标');
    MODE = 'ok'; await ragSearch();
    check(out().includes('最佳匹配'), '渲染了「最佳匹配」分组');
    check(out().includes('寄り返す波が') || out().includes('り返す'), '目标歌词行出现在结果里');
    check(out().includes('精确命中'), '精确命中带徽标');
    check(!out().includes('没有找到相关内容'), '有结果时不显示空状态');

    console.log('\n[UI-2] 后端返回 HTML 错误页：给人话，不再是 Unexpected token');
    MODE = 'html500'; await ragSearch();
    check(out().includes('检索失败'), '显示检索失败');
    check(!out().includes('Unexpected token'), '不再把浏览器原生 SyntaxError 抛给用户');
    check(!out().includes('DOCTYPE'), '不泄漏 HTML 错误页内容');
    check(out().includes('服务器内部出错') && out().includes('500'), '说明是服务端 500 并给出下一步');

    console.log('\n[UI-3] 后端返回 JSON 错误：直接显示后端给的中文说明');
    MODE = 'json500'; await ragSearch();
    check(out().includes('服务器内部错误'), '显示后端下发的中文错误');
    check(!out().includes('Unexpected token'), '不出现解析异常');

    console.log('\n[UI-4] 索引预热中：说「索引正在建立」，不谎报「没有找到」');
    MODE = 'warming'; await ragSearch();
    check(out().includes('索引正在建立中'), '提示索引正在建立');
    check(out().includes('重试'), '给出重试按钮');
    check(!out().includes('没有找到相关内容'), '不再误报「没有找到相关内容」');

    console.log('\n[UI-5] 被自己的筛选挡住：说清楚哪儿其实有，并给一键放开');
    MODE = 'excluded'; await ragSearch();
    check(out().includes('歌词') && out().includes('1 条'), '指出歌词里其实有 1 条命中');
    check(out().includes('完全包含这句话'), '标明那是精确命中');
    check(out().includes(LINE), '给出命中样例原文');
    check(out().includes('ragSearchAllSources'), '提供「放开全部来源重搜」按钮');
    check(typeof ragSearchAllSources === 'function', 'ragSearchAllSources 已定义（按钮不会点了没反应）');

    console.log('\n[UI-6] 真的没有：保留原提示 + 可操作按钮');
    MODE = 'empty'; await ragSearch();
    check(out().includes('没有找到相关内容'), '真没有时如实说没有');
    check(out().includes('去掉课本限定重搜'), '附带可操作建议按钮');

    console.log('\n[UI-7] 响应里缺 results（旧后端/部分失败）：用 lyrics 兜底渲染，绝不说「没有找到」');
    MODE = 'legacy'; await ragSearch();
    check(!out().includes('没有找到相关内容'), '有 lyrics 时不显示空状态');
    check(out().includes('最佳匹配'), '用 lyrics 兜底渲染出结果');

    console.log('\n[UI-8] 一键放开来源：恢复三来源并重搜');
    MODE = 'ok';
    ragSrcOrder = ['textbook'];
    await ragSearchAllSources();
    await new Promise(r => setTimeout(r, 20));
    check(JSON.stringify(ragSrcOrder) === JSON.stringify(['lyric', 'textbook', 'web']),
      '来源恢复为 歌词/课本/网络语料 三选');
    check(JSON.parse(localStorage.getItem('ragBooks') || '[]').length === 0, '课本限定被清空');
  } catch (e) {
    console.log('运行时异常:', (e && e.stack) || e);
    FAILS.push('运行时异常: ' + (e && e.message));
  }
  console.log('\n' + '='.repeat(56));
  if (FAILS.length) { console.log(`RAG UI 测试失败 ${FAILS.length} 项`); FAILS.forEach(f => console.log(' -', f)); process.exit(1); }
  console.log('RAG UI 全部通过（8 组前端行为断言）');
  process.exit(0);        // 页面脚本会留下轮询定时器，测完直接收工，别让 CI 干等
})();
