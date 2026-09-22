# -*- coding: utf-8 -*-
"""
日语汉字注音 API —— 独立轻量服务（给面试官测试用）

只依赖 furigana.py（注音引擎）+ flask，不依赖数据库/后台抓取/TTS，
因此部署快、冷启动快。核心能力：传一段日文文本 → 返回每个词/每个字的读音。

本地运行：
    pip install flask fugashi unidic-lite
    python furigana_api.py
    # 打开 http://localhost:5000 有可视化测试页

API 用法：
    POST /api/furigana    body={"text":"今日は良い天気ですね。"}
    POST /api/annotate    body={"text":"..."}   （返回完整 token，兼容主程序格式）
"""
import furigana
from flask import Flask, request, jsonify, Response

app = Flask(__name__)

MAX_LEN = 30000

INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>日语汉字注音 API</title>
<style>
  :root{--bg:#faf6ef;--card:#fff;--line:#e8e0d0;--ink:#3a3329;--sub:#9a8f7c;--accent:#b4552d;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
       font-family:"Segoe UI","Hiragino Sans","Microsoft YaHei",sans-serif}
  .wrap{max-width:760px;margin:0 auto;padding:32px 20px 60px}
  h1{font-size:24px;margin:0 0 6px}
  .sub{color:var(--sub);font-size:13.5px;margin-bottom:20px;line-height:1.7}
  textarea{width:100%;min-height:120px;padding:12px 14px;font-size:16px;
           border:1px solid var(--line);border-radius:10px;background:var(--card);
           resize:vertical;line-height:1.9;font-family:inherit}
  .row{margin-top:12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  button{background:var(--accent);color:#fff;border:none;padding:9px 22px;
         border-radius:8px;font-size:15px;cursor:pointer}
  button:hover{opacity:.9}
  .hint{color:var(--sub);font-size:12.5px}
  #out{margin-top:20px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;
        padding:18px 20px;margin-top:14px}
  .jp{font-size:20px;line-height:2.2}
  ruby rt{font-size:11px;color:var(--accent)}
  .muted{color:var(--sub);font-size:13px}
  .label{font-size:12px;color:var(--sub);margin:0 0 8px;letter-spacing:.5px}
  .seg{display:inline-block;margin:2px 6px 2px 0}
  .seg .r{color:var(--accent);font-size:13px}
  pre{background:#2b2620;color:#e8e0d0;border-radius:10px;padding:14px 16px;
      overflow:auto;font-size:12.5px;line-height:1.6}
  .endpoint{background:var(--card);border:1px solid var(--line);border-radius:10px;
            padding:10px 14px;margin-top:8px;font-family:ui-monospace,Consolas,monospace;
            font-size:13px}
</style>
</head>
<body>
<div class="wrap">
  <h1>日语汉字注音 API</h1>
  <div class="sub">输入一段日文，自动为每个词、每个汉字标注平假名读音。<br>
    也可直接 POST <code>/api/furigana</code>，body 为 <code>{"text":"..."}</code>。</div>

  <textarea id="t" placeholder="例：今日は良い天気ですね。図書館で勉強する。">六千人の学生が競争する。</textarea>
  <div class="row">
    <button onclick="run()">注音</button>
    <span class="hint" id="status"></span>
  </div>

  <div id="out"></div>

  <div class="card">
    <div class="label">接口</div>
    <div class="endpoint">POST /api/furigana</div>
    <div class="endpoint">POST /api/annotate</div>
    <div class="muted" style="margin-top:8px">返回 JSON，含 segments（逐片段读音）、words（词读音）、chars（逐字读音）三档粒度。</div>
  </div>
</div>
<script>
async function run(){
  const t=document.getElementById('t').value.trim();
  const out=document.getElementById('out');
  const st=document.getElementById('status');
  if(!t){out.innerHTML='';return;}
  st.textContent='注音中…';
  try{
    const r=await fetch('/api/furigana',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text:t})});
    const d=await r.json();
    st.textContent='';
    const segs=d.segments.map(s=>`<span class="seg">${s.r?`<ruby>${esc(s.s)}<rt>${esc(s.r)}</rt></ruby>`:esc(s.s)}</span>`).join('');
    const words=d.words.map(w=>`<span class="seg">${esc(w.word)}<span class="r">（${esc(w.reading)}）</span></span>`).join('');
    const chars=d.chars.map(c=>`<span class="seg">${esc(c.char)}<span class="r"> ${esc(c.reading)}</span></span>`).join('');
    out.innerHTML=`<div class="card"><div class="label">原文注音</div><div class="jp">${segs}</div></div>
      <div class="card"><div class="label">词 · 读音</div><div class="jp" style="font-size:16px">${words}</div></div>
      <div class="card"><div class="label">字 · 读音</div><div class="jp" style="font-size:16px">${chars}</div></div>
      <div class="card"><div class="label">JSON</div><pre>${esc(JSON.stringify(d,null,2))}</pre></div>`;
  }catch(e){st.textContent='请求失败：'+e;}
}
function esc(s){return (s??'').toString().replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
</script>
</body>
</html>"""


@app.route('/')
def index():
    return Response(INDEX_HTML, mimetype='text/html')


@app.after_request
def _cors(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    resp.headers['Access-Control-Allow-Methods'] = 'POST,GET,OPTIONS'
    return resp


@app.route('/api/furigana', methods=['POST', 'OPTIONS'])
def api_furigana():
    if request.method == 'OPTIONS':
        return ('', 204)
    text = (request.get_json(silent=True) or {}).get('text', '')
    if not text or not text.strip():
        return jsonify({'error': 'text 不能为空'}), 400
    if len(text) > MAX_LEN:
        return jsonify({'error': f'文本过长（最多 {MAX_LEN} 字）'}), 400

    tokens = furigana.annotate(text)
    # 一、逐片段读音（含假名片段，reading 为 null 表示无需注音）
    segments = [{'s': t['s'], 'r': t.get('r')} for t in tokens]
    # 二、词读音（去重，优先词典原形）
    words, seen = [], set()
    for t in tokens:
        if not t.get('r'):
            continue
        w = t.get('dw') or t.get('w') or t['s']
        wr = t.get('dr') or t.get('wr') or t.get('r')
        if w and (w, wr) not in seen:
            seen.add((w, wr))
            words.append({'word': w, 'reading': wr})
    # 三、逐字读音（字素对齐，学习工具单字假名标注用）
    chars = [{'char': c, 'reading': r} for c, r in furigana.extract_char_readings(tokens)]
    return jsonify({'text': text, 'segments': segments, 'words': words, 'chars': chars})


@app.route('/api/annotate', methods=['POST', 'OPTIONS'])
def api_annotate():
    if request.method == 'OPTIONS':
        return ('', 204)
    text = (request.get_json(silent=True) or {}).get('text', '')
    if not text:
        return jsonify({'lines': []})
    if len(text) > MAX_LEN:
        return jsonify({'error': f'文本过长（最多 {MAX_LEN} 字）'}), 400
    lines = [furigana.annotate(line) if line.strip() else [] for line in text.split('\n')]
    return jsonify({'lines': lines})


if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, threaded=True)
