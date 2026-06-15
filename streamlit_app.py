#!/usr/bin/env python3
# ── 锐明 PM 工作台 · Streamlit Community Cloud build ─────────────────────────
# Wraps the exact Flask UI for Streamlit Cloud. Gates on Streamax email
# (SMTP login to mail.streamax.com), then injects a `window.BOOT` payload +
# the Anthropic key and embeds templates/index.html unchanged. In this mode
# the page's fetch() shim (in index.html) serves /api/* from BOOT and calls
# the Anthropic API directly from the browser.
#
# Deploy: push this repo to GitHub → Streamlit Community Cloud → main file
# `streamlit_app.py`. Set secrets ANTHROPIC_API_KEY (and optionally
# rebuild data with build_streamlit_data.py when skills/products change).
# ───────────────────────────────────────────────────────────────────────────
import os
import re
import ssl
import json
import base64
import smtplib
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

HERE = Path(__file__).resolve().parent
DATA = HERE / "streamlit_data"
TEMPLATE = HERE / "templates" / "index.html"

st.set_page_config(page_title="锐明 PM 工作台", page_icon=str(DATA / "mascot.png"),
                   layout="wide", initial_sidebar_state="collapsed")

# Strip Streamlit chrome/padding so the embedded app fills the viewport.
st.markdown("""
<style>
  #MainMenu, header, footer {visibility:hidden;}
  .stApp {background:#0b1120;}
  .block-container {padding:0 !important; max-width:100% !important;}
  [data-testid="stHeader"]{height:0;}
  iframe {border:none !important;}
  [data-testid="stMainBlockContainer"]{padding:0 !important;}
</style>
""", unsafe_allow_html=True)


# ── Secrets / config ────────────────────────────────────────────────────────
def secret(name, default=""):
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.environ.get(name, default)


# ── Streamax email login (SMTP auth to mail.streamax.com) ───────────────────
def verify_streamax_credentials(email, password):
    clean = (email or "").strip()
    low = clean.lower()
    # test bypass accounts (same as the Sales Toolkit)
    bypass = {"test": "Test", "jerry_test": "Jerry", "hekun_test": "Hekun", "zntang_test": "ZNTang",
              "jhsun_test": "JHSun", "test_account": "Success"}
    if low in bypass and password == "testme":
        return True, bypass[low]
    if not low.endswith("@streamax.com"):
        return False, "请使用有效的 @streamax.com 邮箱。"
    if not password:
        return False, "密码不能为空。"
    try:
        ctx = ssl.create_default_context()
        server = smtplib.SMTP_SSL("mail.streamax.com", 465, timeout=12, context=ctx)
        server.login(clean, password)
        server.quit()
        return True, clean.split("@")[0]
    except smtplib.SMTPAuthenticationError:
        return False, "邮箱或密码不正确。"
    except Exception as e:  # noqa: BLE001
        if "535" in str(e) or "authentication failed" in str(e).lower():
            return False, "邮箱或密码不正确。"
        return False, f"无法连接邮件服务器：{e}"


def render_login():
    st.markdown("""
    <style>
      .login-wrap{max-width:380px;margin:8vh auto 0;text-align:center;color:#eaf0fb;
        font-family:"DM Sans","PingFang SC",sans-serif;}
      .login-wrap img{width:88px;height:88px;filter:drop-shadow(0 4px 12px rgba(0,0,0,.5));}
      .login-wrap h1{font-family:"Space Grotesk",sans-serif;font-size:24px;margin:14px 0 4px;}
      .login-wrap p{color:#94a3b8;font-size:13px;margin:0 0 6px;}
    </style>
    """, unsafe_allow_html=True)
    mascot_uri = data_uri(DATA / "mascot.png", "image/png")
    st.markdown(f"""<div class="login-wrap"><img src="{mascot_uri}">
      <h1>锐明 PM 工作台</h1><p>请使用 Streamax 邮箱登录</p></div>""", unsafe_allow_html=True)
    c = st.columns([1, 2, 1])[1]
    with c:
        with st.form("login", clear_on_submit=False):
            email = st.text_input("邮箱", placeholder="yourname@streamax.com")
            pw = st.text_input("密码", type="password")
            ok = st.form_submit_button("登录", use_container_width=True)
        if ok:
            valid, msg = verify_streamax_credentials(email, pw)
            if valid:
                st.session_state.authed = True
                st.session_state.user = msg
                st.rerun()
            else:
                st.error(msg)


# ── Bundle loading ──────────────────────────────────────────────────────────
def data_uri(path, mime):
    return f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode()


@st.cache_data(show_spinner=False)
def load_bundle():
    pm = json.loads((DATA / "pmskills.json").read_text(encoding="utf-8"))
    pedia = json.loads((DATA / "streamaxpedia.json").read_text(encoding="utf-8"))
    models = json.loads((DATA / "models.json").read_text(encoding="utf-8"))
    prod_meta = json.loads((DATA / "products.json").read_text(encoding="utf-8"))["products"]
    products = [{
        "id": p["id"], "title": p["title"],
        "image": data_uri(DATA / "products" / p["file"], "image/jpeg"),
    } for p in prod_meta]
    return {
        "catalog": pm["modules"],
        "bodies": pm["bodies"],
        "persona": (DATA / "persona.txt").read_text(encoding="utf-8"),
        "systemKnowledge": (DATA / "system_knowledge.md").read_text(encoding="utf-8"),
        "streamaxpedia": pedia,
        "products": products,
        "models": models["models"],
        "default_model": models["default"],
        "mascot": data_uri(DATA / "mascot.png", "image/png"),
    }


def render_app():
    boot = dict(load_bundle())
    boot["apiKey"] = secret("ANTHROPIC_API_KEY")
    if not boot["apiKey"]:
        st.error("未配置 ANTHROPIC_API_KEY（请在 Streamlit Secrets 中设置）。")
        return

    html = TEMPLATE.read_text(encoding="utf-8")
    # render the model <select> options (replaces the Flask Jinja loop)
    opts = "".join(
        f'<option value="{mid}"{" selected" if mid == boot["default_model"] else ""}>{label}</option>'
        for mid, label in boot["models"].items())
    html = re.sub(r"\{%\s*for mid.*?\{%\s*endfor\s*%\}", opts, html, flags=re.S)
    # inject BOOT as the LAST thing in <head> so the fetch shim sees it.
    # IMPORTANT: replace only the FIRST </head> — the template also contains a
    # literal "</head>" inside the exportDoc JS string; replacing all of them
    # would inject the script into the middle of the main <script> and break it.
    # Also escape "</" in the JSON so embedded content can't close the tag early.
    boot_json = (json.dumps(boot, ensure_ascii=False)
                 .replace("</", "<\\/").replace(" ", "\\u2028").replace(" ", "\\u2029"))
    html = html.replace("</head>", "<script>window.BOOT=" + boot_json + ";</script></head>", 1)
    # resolve mascot references to the inlined data URI
    html = html.replace("/assets/mascot.png", boot["mascot"])

    components.html(html, height=900, scrolling=False)


# ── Entry ───────────────────────────────────────────────────────────────────
if not st.session_state.get("authed"):
    render_login()
else:
    render_app()
