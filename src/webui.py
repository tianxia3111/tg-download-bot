import json
import logging
import os
import re
import secrets
import time
from functools import wraps
from pathlib import Path

import requests
from flask import Flask, request, session, redirect, url_for, render_template_string

logging.getLogger("werkzeug").setLevel(logging.ERROR)

CONFIG_FILE = Path(__file__).parent.parent / "config.env"

SECTIONS = [
    {
        "icon": "&#9889;",
        "title": "消息通知",
        "fields": [
            {"key": "BOT_TOKEN", "label": "Telegram Bot Token", "ph": "123456:ABC-DEF", "btn": None},
            {"key": "PROXY_URL", "label": "代理地址", "note": "留空则不使用代理", "ph": "http://proxy:port", "btn": "test-proxy"},
            {"key": "POLL_INTERVAL", "label": "轮询间隔 (秒)", "ph": "3", "btn": None},
        ],
    },
    {
        "icon": "&#9889;",
        "title": "Gopeed 下载器",
        "fields": [
            {"key": "GOPEED_URL", "label": "API 地址", "ph": "http://127.0.0.1:9999", "btn": None},
            {"key": "GOPEED_TOKEN", "label": "API Token", "ph": "输入 Token", "btn": None},
        ],
    },
    {
        "icon": "&#128451;",
        "title": "存储路径",
        "fields": [
            {"key": "AV_DEST", "label": "AV 目标目录", "ph": "/path/to/av", "btn": None},
            {"key": "BT_DEST", "label": "电影 / 剧集目标目录", "ph": "/path/to/movies", "btn": None},
        ],
    },
    {
        "icon": "&#129504;",
        "title": "AI 智能分析",
        "fields": [
            {"key": "AI_API_URL", "label": "API 地址", "note": "OpenAI / Anthropic 自动识别", "ph": "https://api.xxx.com/v1", "btn": None},
            {"key": "AI_API_KEY", "label": "API Key", "ph": "sk-xxx", "btn": None},
            {"key": "AI_MODEL", "label": "模型名称", "ph": "输入模型名称", "btn": "fetch-models"},
        ],
    },
    {
        "icon": "&#128270;",
        "title": "HGME 资源搜索",
        "fields": [
            {"key": "HGME_ENABLED", "label": "启用 HGME 搜索", "ph": "true", "btn": None},
            {"key": "HGME_USERNAME", "label": "用户名", "ph": "输入用户名", "btn": None},
            {"key": "HGME_PASSWORD", "label": "密码", "ph": "", "btn": None},
        ],
    },
    {
        "icon": "&#128274;",
        "title": "账号安全",
        "fields": [
            {"key": "WEBUI_USERNAME", "label": "WebUI 用户名", "ph": "输入用户名", "btn": None},
            {"key": "WEBUI_PASSWORD", "label": "WebUI 密码", "ph": "输入新密码", "btn": None},
        ],
    },
]

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", secrets.token_hex(32))

WEBUI_USERNAME = os.getenv("WEBUI_USERNAME", "")
WEBUI_PASSWORD = os.getenv("WEBUI_PASSWORD", "")

CSS = r"""
:root{--bg:#f6f8fa;--surface:#fff;--border:#d0d7de;--text:#1f2328;--muted:#656d76;--accent:#0969da;--red:#cf222e;--green:#1a7f37;--radius:12px;--shadow:0 1px 3px rgba(0,0,0,.06),0 1px 2px rgba(0,0,0,.04)}
.dark{--bg:#0d1117;--surface:#161b22;--border:#30363d;--text:#c9d1d9;--muted:#8b949e;--accent:#58a6ff;--red:#f85149;--green:#3fb950;--shadow:0 1px 3px rgba(0,0,0,.3),0 1px 2px rgba(0,0,0,.2)}
*{margin:0;padding:0;box-sizing:border-box}
body{font:14px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;transition:background .3s,color .3s}
.header{background:var(--surface);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:10;backdrop-filter:blur(12px)}
.header-inner{max-width:760px;margin:0 auto;padding:14px 24px;display:flex;align-items:center;justify-content:space-between}
.logo{display:flex;align-items:center;gap:10px}
.logo h1{font-size:18px;font-weight:700}
.logo span{font-size:26px}
.theme-btn{width:36px;height:36px;border-radius:50%;border:1px solid var(--border);background:var(--surface);color:var(--text);cursor:pointer;font-size:18px;display:flex;align-items:center;justify-content:center;transition:all .2s}
.theme-btn:hover{background:var(--border)}
.container{max-width:760px;margin:0 auto;padding:24px}
.hero{text-align:center;padding:32px 0 16px}
.hero h2{font-size:24px;font-weight:700;margin-bottom:6px}
.hero p{font-size:14px;color:var(--muted)}
.section{margin-bottom:20px}
.section-header{display:flex;align-items:center;gap:8px;margin-bottom:10px;padding:0 4px}
.section-header .icon{font-size:18px}
.section-header h3{font-size:13px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.6px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow);overflow:hidden}
.row{display:flex;align-items:center;padding:14px 18px;border-bottom:1px solid var(--border);gap:14px;transition:background .15s}
.row:last-child{border-bottom:none}
.row:hover{background:var(--bg)}
.row-label{flex:0 0 160px}
.row-label label{font-size:13px;font-weight:500}
.row-note{font-size:11px;color:var(--muted);margin-top:2px}
.row-input{flex:1;display:flex;gap:8px;align-items:center}
.row-input input{flex:1;padding:9px 14px;border:1.5px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text);font-size:13px;font-family:ui-monospace,SFMono-Regular,monospace;transition:all .2s}
.row-input input:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px rgba(9,105,218,.12)}
.row-input input::placeholder{color:var(--muted);font-family:inherit}
.row-input select{flex:1;padding:9px 14px;border:1.5px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text);font-size:13px;font-family:ui-monospace,monospace;transition:all .2s;appearance:none;cursor:pointer}
.row-input select:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px rgba(9,105,218,.12)}
.inline-btn{flex-shrink:0;padding:7px 14px;border-radius:6px;font-size:12px;font-weight:500;cursor:pointer;border:1.5px solid var(--border);background:var(--surface);color:var(--text);white-space:nowrap;transition:all .15s}
.inline-btn:hover{background:var(--border)}
.inline-btn.loading{opacity:.6;pointer-events:none}
.actions{margin-top:16px}
.btn-primary{padding:11px 28px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;border:none;transition:all .15s;background:var(--accent);color:#fff}
.btn-primary:hover{filter:brightness(1.1)}
.btn-outline{padding:11px 28px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;border:1.5px solid var(--border);background:var(--surface);color:var(--text);transition:all .15s}
.btn-outline:hover{background:var(--border)}
.toast{position:fixed;bottom:28px;right:28px;padding:14px 24px;border-radius:10px;font-size:13px;font-weight:500;box-shadow:0 8px 24px rgba(0,0,0,.25);opacity:0;transform:translateY(12px);transition:all .35s cubic-bezier(.4,0,.2,1);pointer-events:none;z-index:100;letter-spacing:.2px}
.toast.show{opacity:1;transform:translateY(0)}
.toast.ok{background:var(--green);color:#fff}
.toast.err{background:var(--red);color:#fff}
.status{margin-top:4px;font-size:11px}
.status.ok{color:var(--green)}
.status.err{color:var(--red)}
.login-page{display:flex;align-items:center;justify-content:center;min-height:100vh;padding:24px}
.login-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow);padding:40px;width:100%;max-width:380px}
.login-card h2{text-align:center;font-size:22px;margin-bottom:24px}
.login-card label{display:block;font-size:13px;font-weight:500;margin-bottom:4px}
.login-card input{width:100%;padding:10px 14px;border:1.5px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text);font-size:14px;margin-bottom:16px;transition:all .2s;box-sizing:border-box}
.login-card input:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px rgba(9,105,218,.12)}
.login-card .btn-primary{width:100%;padding:12px;font-size:14px;margin-top:4px}
.login-error{text-align:center;color:var(--red);font-size:13px;margin-bottom:12px}
"""

CONFIG_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN" class="{{ 'dark' if dark else '' }}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TG-Download-Bot — 配置中心</title>
<style>{{ css }}</style>
</head>
<body>
<div class="header"><div class="header-inner">
<div class="logo"><span>&#129302;</span><h1>TG-Download-Bot</h1></div>
<button class="theme-btn" onclick="toggleTheme()" id="tbtn">&#9728;&#65039;</button>
</div></div>

<div class="container">
<div class="hero">
<h2>配置中心</h2>
<p>大部分配置需重启生效，账号安全设置保存后即时生效</p>
</div>

<form id="form">
{% for sec in sections %}
<div class="section">
<div class="section-header"><span class="icon">{{ sec.icon|safe }}</span><h3>{{ sec.title }}</h3></div>
<div class="card">
{% for f in sec.fields %}
<div class="row">
<div class="row-label"><label>{{ f.label }}</label>{% if f.note %}<div class="row-note">{{ f.note }}</div>{% endif %}</div>
<div class="row-input">
{% if f.key == 'AI_MODEL' %}
<select name="{{ f.key }}" id="model-select">
<option value="{{ values.get(f.key,'') }}">{{ values.get(f.key,'') or '-- 请先获取模型列表 --' }}</option>
</select>
{% else %}
<input name="{{ f.key }}" value="{{ values.get(f.key,'') }}" placeholder="{{ f.ph }}" type="{{ 'password' if 'KEY' in f.key or 'TOKEN' in f.key else 'text' }}" autocomplete="off" spellcheck="false">
{% endif %}
{% if f.btn == 'fetch-models' %}
<button type="button" class="inline-btn" onclick="fetchModels()" id="btn-fetch-models">获取模型</button>
{% elif f.btn == 'test-proxy' %}
<button type="button" class="inline-btn" onclick="testProxy()" id="btn-test-proxy">测试连接</button>
<div class="status" id="proxy-status"></div>
{% endif %}
</div>
</div>
{% endfor %}
</div>
</div>
{% endfor %}

<div class="actions">
<button type="submit" class="btn btn-primary">保存配置</button>
<button type="button" class="btn btn-outline" onclick="restart()" id="restart-btn">重启容器</button>
</div>
</form>
</div>

<div class="toast" id="toast"></div>

<script>
var dark = localStorage.getItem('theme') === 'dark';
if(dark) document.documentElement.classList.add('dark');
document.getElementById('tbtn').innerHTML = dark ? '&#9790;' : '&#9728;&#65039;';
function toggleTheme(){
dark=!dark;document.cookie='theme='+(dark?'dark':'light')+';path=/;max-age=31536000';
document.documentElement.classList.toggle('dark',dark);
document.getElementById('tbtn').innerHTML=dark?'&#9790;':'&#9728;&#65039;';
}
function toast(m,ok){var t=document.getElementById('toast');t.textContent=m;t.className='toast '+(ok?'ok':ok===false?'err':'ok');t.classList.add('show');setTimeout(function(){t.classList.remove('show')},3000)}
async function restart(){
if(!confirm('确认重启容器？Bot 会断连几秒后自动恢复。'))return;
var btn=document.getElementById('restart-btn');btn.textContent='重启中...';btn.disabled=true;
try{await fetch('/restart',{method:'POST'});}catch(e){}
setTimeout(function(){location.reload()},5000);
}

document.getElementById('form').addEventListener('submit', async function(e){
e.preventDefault();
var btn=this.querySelector('button[type=submit]');btn.textContent='保存中...';btn.disabled=true;
var data=new FormData(this);
try{
var r=await fetch('/save',{method:'POST',body:data});
var d=await r.json();
if(d.ok){toast('配置已保存，重启后生效');}else{toast(d.error||'保存失败',false)}
}catch(e){toast('请求失败',false)}
btn.textContent='保存配置';btn.disabled=false;
});

async function testProxy(){
var btn=document.getElementById('btn-test-proxy'),st=document.getElementById('proxy-status');
btn.textContent='测试中...';btn.classList.add('loading');st.textContent='';st.className='status';
var proxy=document.querySelector('input[name="PROXY_URL"]').value;
try{
var r=await fetch('/api/test-proxy',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({proxy:proxy})});
var d=await r.json();
if(d.ok){st.textContent='连接成功 ('+d.latency+'ms)';st.className='status ok';toast('代理连接成功')}
else{st.textContent=d.error;st.className='status err';toast(d.error,false)}
}catch(e){st.textContent='请求失败';st.className='status err'}
btn.textContent='测试连接';btn.classList.remove('loading');
}

async function fetchModels(){
var btn=document.getElementById('btn-fetch-models'),sel=document.getElementById('model-select');
btn.textContent='获取中...';btn.classList.add('loading');
var url=document.querySelector('input[name="AI_API_URL"]').value;
var key=document.querySelector('input[name="AI_API_KEY"]').value;
if(!url||!key){toast('请先填写 API 地址和 Key',false);btn.textContent='获取模型';btn.classList.remove('loading');return}
try{
var r=await fetch('/api/models',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:url,key:key})});
var d=await r.json();
sel.innerHTML='';
if(d.models && d.models.length){
d.models.forEach(function(m){var o=document.createElement('option');o.value=m;o.textContent=m;if(m===sel.getAttribute('data-current'))o.selected=true;sel.appendChild(o)});
toast('获取到 '+d.models.length+' 个模型')
}else{toast(d.error||'未找到模型',false)}
}catch(e){toast('请求失败',false)}
btn.textContent='获取模型';btn.classList.remove('loading');
}
document.getElementById('model-select').setAttribute('data-current','{{ values.get("AI_MODEL","") }}');
</script>
</body>
</html>"""

LOGIN_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN" class="{{ 'dark' if dark else '' }}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TG-Download-Bot — 登录</title>
<style>{{ css }}</style>
</head>
<body class="login-page">
<div class="login-card">
<h2>&#129302; TG-Download-Bot</h2>
{% if error %}<div class="login-error">{{ error }}</div>{% endif %}
<form method="post" action="/login">
<label>用户名</label>
<input name="username" type="text" autocomplete="username" required>
<label>密码</label>
<input name="password" type="password" autocomplete="current-password" required>
<button type="submit" class="btn-primary">登 录</button>
</form>
</div>
<script>
var dark = localStorage.getItem('theme') === 'dark';
if(dark) document.documentElement.classList.add('dark');
</script>
</body>
</html>"""


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated


def load_config():
    values = {}
    if CONFIG_FILE.exists():
        for line in CONFIG_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def save_config(data):
    global WEBUI_USERNAME, WEBUI_PASSWORD
    existing = {}
    if CONFIG_FILE.exists():
        for line in CONFIG_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                existing[k.strip()] = v.strip().strip('"').strip("'")

    for sec in SECTIONS:
        for f in sec["fields"]:
            v = data.get(f["key"])
            if v is not None:
                v = v.strip()
                if v:
                    existing[f["key"]] = v
                else:
                    existing.pop(f["key"], None)

    if "WEBUI_USERNAME" in existing:
        WEBUI_USERNAME = existing["WEBUI_USERNAME"]
    if "WEBUI_PASSWORD" in existing:
        WEBUI_PASSWORD = existing["WEBUI_PASSWORD"]

    lines = [f'{k}={v}' for k, v in existing.items()]
    CONFIG_FILE.write_text("\n".join(lines) + "\n")


@app.route("/login", methods=["GET", "POST"])
def login_page():
    dark = request.cookies.get("theme", "dark") == "dark"
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == WEBUI_USERNAME and password == WEBUI_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("index"))
        error = "用户名或密码错误"
    return render_template_string(LOGIN_HTML, css=CSS, error=error, dark=dark)


@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("login_page"))


@app.route("/")
@login_required
def index():
    dark = request.cookies.get("theme", "dark") == "dark"
    return render_template_string(CONFIG_HTML, css=CSS, sections=SECTIONS, values=load_config(), dark=dark)


@app.route("/save", methods=["POST"])
@login_required
def save():
    try:
        save_config(request.form)
        return {"ok": True}
    except Exception as e:
        logging.getLogger("tg-download-bot").warning("Save config error: %s", e)
        return {"ok": False, "error": str(e)[:120]}


@app.route("/api/test-proxy", methods=["POST"])
@login_required
def api_test_proxy():
    data = request.get_json(force=True)
    proxy_url = (data.get("proxy") or "").strip()
    if not proxy_url:
        return {"ok": False, "error": "未填写代理地址"}
    proxies = {"http": proxy_url, "https": proxy_url}
    try:
        t0 = time.time()
        r = requests.get("https://www.baidu.com", proxies=proxies, timeout=8)
        latency = int((time.time() - t0) * 1000)
        if r.status_code == 200:
            return {"ok": True, "latency": latency}
        return {"ok": False, "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:80]}


@app.route("/api/models", methods=["POST"])
@login_required
def api_models():
    data = request.get_json(force=True)
    api_url = (data.get("url") or "").strip().rstrip("/")
    api_key = (data.get("key") or "").strip()
    if not api_url or not api_key:
        return {"models": [], "error": "请填写 API 地址和 Key"}
    try:
        models = _fetch_models(api_url, api_key)
        return {"models": models}
    except Exception as e:
        return {"models": [], "error": str(e)[:120]}


def _fetch_models(api_url, api_key):
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    base = api_url.strip().rstrip("/")
    if "://" in base:
        proto, rest = base.split("://", 1)
        host, _, path = rest.partition("/")
        base = f"{proto}://{host}/{path.lower()}" if path else f"{proto}://{host}"

    candidates = [base + "/v1/models", base + "/models"]

    if "minimaxi.com" in base or "minimax.io" in base:
        v1 = re.sub(r"/anthropic", "/v1", base, flags=re.I)
        if v1 != base:
            candidates.insert(0, v1 + "/models")

    for url in candidates:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code != 200:
                continue
            data = r.json()
            models = []
            for item in data.get("data", data.get("models", [])):
                mid = item.get("id") or item.get("name") or item.get("model", "")
                if mid and "embed" not in mid.lower() and "moderation" not in mid.lower():
                    models.append(mid)
            models.sort()
            if models:
                return models[:30]
        except Exception:
            continue
    raise Exception("无法获取模型列表，请检查 API 地址和 Key")


@app.route("/restart", methods=["POST"])
@login_required
def restart_container():
    import os as _os
    _os._exit(0)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9099, debug=False)
