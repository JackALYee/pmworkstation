#!/usr/bin/env python3
# ── 锐明 PM 工作台 / Streamax PM Workbench ─────────────────────────────────
# Local Flask app: serves the workbench UI, proxies the Claude API (key stays
# server-side), and reads the PM skill library + Streamax product knowledge
# live from disk so edits to those files show up without a rebuild.
# Run:  python server.py   →  http://127.0.0.1:7860
# ───────────────────────────────────────────────────────────────────────────

import os
import re
import sys
import json
import mimetypes
from pathlib import Path

from flask import Flask, request, Response, jsonify, send_file, render_template

import anthropic

# ── Paths (absolute — this app stitches together three sibling repos) ───────
HERE = Path(__file__).resolve().parent
PM_SKILLS_DIR = Path("/Users/jiachenyi/Documents/AI Skill/pm-skills")
STREAMAX_SKILL = Path(
    "/Users/jiachenyi/Desktop/Streamax/Sales Toolkit/auto email/.claude/skills/streamax-knowledge"
)
JERRY_KNOWLEDGE = Path(
    "/Users/jiachenyi/Desktop/Streamax/Sales Toolkit/salestoolkit/jerry_gpt_knowledge"
)
PRODUCT_IMAGES = Path(
    "/Users/jiachenyi/Desktop/Streamax/Sales Toolkit/salestoolkit/assets/products"
)
# Streamaxpedia product DB (115 SKUs + downloadable spec-sheet / user-manual URLs)
# lives in salestoolkit/terminology_db.py — shared with Jerry GPT.
SALESTOOLKIT_DIR = Path("/Users/jiachenyi/Desktop/Streamax/Sales Toolkit/salestoolkit")
API_KEY_FILE = HERE / "Claude API PM.md"
I18N_FILE = HERE / "i18n_zh.json"

# Chinese translations of skill/command descriptions, keyed "plugin/kind/name".
try:
    I18N = json.loads(I18N_FILE.read_text(encoding="utf-8")) if I18N_FILE.exists() else {}
except Exception:  # noqa: BLE001
    I18N = {}

# ── Models offered in the UI ────────────────────────────────────────────────
MODELS = {
    "claude-sonnet-4-6": "Sonnet 4.6 · 均衡（默认）",
    "claude-opus-4-8": "Opus 4.8 · 最强",
    "claude-haiku-4-5-20251001": "Haiku 4.5 · 快速",
}
DEFAULT_MODEL = "claude-sonnet-4-6"

# ── Module metadata: Chinese titles, icons, accent colors keyed by plugin ───
# Order + colors mirror the pm-skills marketplace card layout.
MODULE_META = {
    "pm-product-discovery": {"title": "产品发现", "icon": "🔍", "color": "#f97316", "blurb": "创意、实验、假设验证、机会方案树、用户访谈"},
    "pm-product-strategy":  {"title": "产品战略", "icon": "♟️", "color": "#ec4899", "blurb": "愿景、商业模式、定价、SWOT、波特五力、竞争格局"},
    "pm-execution":         {"title": "执行落地", "icon": "🚀", "color": "#3b82f6", "blurb": "PRD、OKR、路线图、冲刺、复盘、发布说明、红队演练"},
    "pm-market-research":   {"title": "市场研究", "icon": "🧭", "color": "#14b8a6", "blurb": "用户画像、细分、旅程地图、市场规模、竞品分析"},
    "pm-data-analytics":    {"title": "数据分析", "icon": "📊", "color": "#22c55e", "blurb": "SQL 生成、留存队列分析、A/B 测试显著性"},
    "pm-go-to-market":      {"title": "走向市场 GTM", "icon": "🎯", "color": "#8b5cf6", "blurb": "滩头市场、ICP、增长飞轮、GTM 打法、竞争对战卡"},
    "pm-marketing-growth":  {"title": "营销增长", "icon": "📣", "color": "#ef4444", "blurb": "营销创意、定位、价值主张、命名、北极星指标"},
    "pm-toolkit":           {"title": "PM 工具箱", "icon": "🧰", "color": "#64748b", "blurb": "简历优化、NDA、隐私政策、文稿校对"},
    "pm-ai-shipping":       {"title": "AI 交付套件", "icon": "📦", "color": "#06b6d4", "blurb": "记录 AI 编写的应用、安全与性能审计、出厂打包"},
}
MODULE_ORDER = list(MODULE_META.keys())

app = Flask(__name__, template_folder=str(HERE / "templates"))

# ── API key + client (lazy) ─────────────────────────────────────────────────
_client = None


def get_client():
    global _client
    if _client is None:
        key = ""
        if API_KEY_FILE.exists():
            # File holds the raw key (possibly with a markdown header). Grab the
            # first sk-ant-... token we can find.
            txt = API_KEY_FILE.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"sk-ant-[A-Za-z0-9_\-]+", txt)
            key = m.group(0) if m else txt.strip()
        key = os.environ.get("ANTHROPIC_API_KEY", key)
        if not key:
            raise RuntimeError("未找到 Anthropic API Key（检查 Claude API PM.md）")
        _client = anthropic.Anthropic(api_key=key)
    return _client


# ── Frontmatter parsing ─────────────────────────────────────────────────────
def parse_frontmatter(text):
    """Return (meta_dict, body) for a markdown file with --- frontmatter."""
    meta, body = {}, text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            fm = text[3:end]
            body = text[end + 4:].lstrip("\n")
            for line in fm.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, body


# ── Catalog: walk the 9 plugins → modules with skills + commands ────────────
def build_catalog():
    modules = []
    for plugin in MODULE_ORDER:
        pdir = PM_SKILLS_DIR / plugin
        if not pdir.exists():
            continue
        meta = MODULE_META[plugin]
        skills, commands = [], []

        sdir = pdir / "skills"
        if sdir.exists():
            for sk in sorted(sdir.iterdir()):
                skill_md = sk / "SKILL.md"
                if skill_md.exists():
                    fm, _ = parse_frontmatter(skill_md.read_text(encoding="utf-8", errors="ignore"))
                    name = fm.get("name", sk.name)
                    en = fm.get("description", "")
                    skills.append({
                        "name": name,
                        "description": en,  # English original (shown in tooltip)
                        "description_zh": I18N.get(f"{plugin}/skill/{name}", ""),
                    })

        cdir = pdir / "commands"
        if cdir.exists():
            for cmd in sorted(cdir.glob("*.md")):
                fm, _ = parse_frontmatter(cmd.read_text(encoding="utf-8", errors="ignore"))
                en = fm.get("description", "")
                commands.append({
                    "name": cmd.stem,
                    "description": en,  # English original (shown in tooltip)
                    "description_zh": I18N.get(f"{plugin}/command/{cmd.stem}", ""),
                    "hint": fm.get("argument-hint", ""),
                })

        modules.append({
            "id": plugin,
            "title": meta["title"],
            "icon": meta["icon"],
            "color": meta["color"],
            "blurb": meta["blurb"],
            "skills": skills,
            "commands": commands,
        })
    return modules


def load_skill_body(plugin, kind, name):
    """Return the full markdown body of a skill or command."""
    pdir = PM_SKILLS_DIR / plugin
    if kind == "command":
        f = pdir / "commands" / f"{name}.md"
    else:
        f = pdir / "skills" / name / "SKILL.md"
    if not f.exists():
        return None
    _, body = parse_frontmatter(f.read_text(encoding="utf-8", errors="ignore"))
    return body


# ── Streamax knowledge (always-on, cached system block) ─────────────────────
_streamax_cache = None


def load_streamax_block():
    """Concatenate the canonical distilled Streamax knowledge (SKILL.md + all
    reference/ files). ~24K tokens — sent once as a cached system block."""
    global _streamax_cache
    if _streamax_cache is not None:
        return _streamax_cache
    parts = []
    skill_md = STREAMAX_SKILL / "SKILL.md"
    if skill_md.exists():
        parts.append(skill_md.read_text(encoding="utf-8", errors="ignore"))
    refdir = STREAMAX_SKILL / "reference"
    if refdir.exists():
        for ref in sorted(refdir.glob("*.md")):
            parts.append(f"\n\n===== reference/{ref.name} =====\n\n" +
                         ref.read_text(encoding="utf-8", errors="ignore"))
    _streamax_cache = "\n\n".join(parts) if parts else "(Streamax 知识库未找到)"
    return _streamax_cache


# ── Streamaxpedia: product DB + spec-sheet / user-manual download URLs ───────
_pedia_cache = None
_pedia_block = None


def load_streamaxpedia():
    """Import terminology_db.py from salestoolkit. Returns the list of product
    entries (term, category, desc, related, files[label/url]). Cached."""
    global _pedia_cache
    if _pedia_cache is not None:
        return _pedia_cache
    try:
        if str(SALESTOOLKIT_DIR) not in sys.path:
            sys.path.insert(0, str(SALESTOOLKIT_DIR))
        import terminology_db as t  # type: ignore
        _pedia_cache = list(t.TERMINOLOGY_DB)
    except Exception:  # noqa: BLE001
        _pedia_cache = []
    return _pedia_cache


import html as _html


def html_to_text(s):
    """Streamaxpedia `desc` fields mix prose with an HTML visual diagram
    (`<div class="diagram-box">…`). Drop the diagram, convert the rest to
    readable plain text (br/li → line breaks, bullets), strip tags, unescape."""
    if not s or "<" not in s:
        return (s or "").strip()
    # cut off the visual diagram block — everything from it on is layout noise
    cut = s.find('<div class="diagram-box"')
    if cut != -1:
        s = s[:cut]
    s = re.sub(r"<\s*br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<\s*/\s*(li|p|div|ul|ol)\s*>", "\n", s, flags=re.I)
    s = re.sub(r"<\s*li[^>]*>", "• ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)          # strip remaining tags
    s = _html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def build_pedia_block():
    """Compact Streamaxpedia snapshot for the always-on system prompt: every SKU
    with its category, one-line desc, and downloadable spec/manual URLs — so the
    AI can hand a PM the exact spec-sheet link on request."""
    global _pedia_block
    if _pedia_block is not None:
        return _pedia_block
    rows = load_streamaxpedia()
    if not rows:
        _pedia_block = ""
        return _pedia_block
    lines = ["# Streamaxpedia 产品规格库（始终生效）",
             "锐明每个产品型号及其规格书/用户手册下载链接。当用户索取某产品的技术规格书时，"
             "直接给出下方对应的 URL（这些是官方可下载链接）。\n"]
    for e in rows:
        term = e.get("term", "")
        cat = e.get("category", "")
        desc = html_to_text(e.get("desc", "")).replace("\n", " ")
        files = e.get("files", []) or []
        flinks = " ; ".join(f"{f.get('label','')}: {f.get('url','')}" for f in files)
        line = f"- **{term}** [{cat}] — {desc}"
        if flinks:
            line += f"  〔{flinks}〕"
        lines.append(line)
    _pedia_block = "\n".join(lines)
    return _pedia_block


# ── Product portfolio (for the Spec lookup module) ──────────────────────────
def slug_to_title(slug):
    return slug.replace("_", " ").upper()


def list_products():
    if not PRODUCT_IMAGES.exists():
        return []
    out = []
    for img in sorted(PRODUCT_IMAGES.glob("*.jpg")):
        out.append({"id": img.stem, "title": slug_to_title(img.stem),
                    "image": f"/product-image/{img.name}"})
    for img in sorted(PRODUCT_IMAGES.glob("*.png")):
        out.append({"id": img.stem, "title": slug_to_title(img.stem),
                    "image": f"/product-image/{img.name}"})
    return out


# ── System prompt assembly ──────────────────────────────────────────────────
PERSONA = """你是「锐明 PM 工作台」内置的资深产品经理 AI 助手，服务于锐明技术（Streamax，SZ:002970）的产品团队。

工作原则：
- 默认使用**简体中文**回答，除非用户用英文提问或明确要求英文输出。
- 你内置了一整套世界级 PM 方法论（产品发现、战略、执行、市场研究、数据分析、GTM、营销增长、工具箱、AI 交付）。当用户加载了某个「技能/命令」时，严格按照该方法论的步骤、框架与产出模板来工作。
- 你始终了解锐明的公司事实、产品组合、规格、定价与竞争格局（见下方知识库）。在产生与产品相关的建议时，**主动引用具体型号、规格、价格与差异化卖点**，不要泛泛而谈。
- 涉及 PRD、路线图、定价、GTM 等产出时，结合锐明真实产品（如 C29N DMS、AD Plus/AD Max 行车记录仪、C53 BSIS、SafeGPT、MDVR 系列等）举例，使产出可直接落地。
- 输出使用清晰的 Markdown：标题、表格、清单。需要时给出可执行的下一步建议。"""


def build_system(skill_body=None, skill_label=None):
    knowledge = "# 锐明产品与销售知识库（始终生效）\n\n" + load_streamax_block()
    pedia = build_pedia_block()
    if pedia:
        knowledge += "\n\n" + pedia
    blocks = [
        {"type": "text", "text": PERSONA},
        {
            "type": "text",
            "text": knowledge,
            "cache_control": {"type": "ephemeral"},
        },
    ]
    if skill_body:
        blocks.append({
            "type": "text",
            "text": (f"# 当前加载的 PM 方法论：{skill_label}\n\n"
                     "请严格依据以下框架与步骤来协助用户。这是本次对话要遵循的工作方法：\n\n"
                     + skill_body),
        })
    return blocks


# ── Routes ──────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html",
                           models=MODELS, default_model=DEFAULT_MODEL)


@app.route("/api/catalog")
def api_catalog():
    return jsonify({"modules": build_catalog()})


@app.route("/api/skill")
def api_skill():
    plugin = request.args.get("plugin", "")
    kind = request.args.get("kind", "skill")
    name = request.args.get("name", "")
    body = load_skill_body(plugin, kind, name)
    if body is None:
        return jsonify({"error": "未找到该技能"}), 404
    return jsonify({"plugin": plugin, "kind": kind, "name": name, "body": body})


@app.route("/api/products")
def api_products():
    return jsonify({"products": list_products()})


@app.route("/api/streamaxpedia")
def api_streamaxpedia():
    """Product DB with downloadable spec-sheet / user-manual URLs."""
    rows = load_streamaxpedia()
    out = [{
        "term": e.get("term", ""),
        "category": e.get("category", ""),
        "desc": html_to_text(e.get("desc", "")),
        "files": e.get("files", []) or [],
    } for e in rows]
    # group categories for UI filtering
    cats = sorted({r["category"] for r in out if r["category"]})
    return jsonify({"products": out, "categories": cats})


@app.route("/assets/<path:fname>")
def asset(fname):
    f = HERE / "assets" / fname
    if not f.exists() or ".." in fname:
        return "not found", 404
    mt, _ = mimetypes.guess_type(str(f))
    return send_file(str(f), mimetype=mt or "application/octet-stream")


@app.route("/product-image/<path:fname>")
def product_image(fname):
    f = PRODUCT_IMAGES / fname
    if not f.exists() or ".." in fname:
        return "not found", 404
    mt, _ = mimetypes.guess_type(str(f))
    return send_file(str(f), mimetype=mt or "image/jpeg")


# ── Attachments → Anthropic content blocks ──────────────────────────────────
IMAGE_MIMES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def _extract_docx(raw):
    try:
        import io, docx  # noqa: PLC0415
        d = docx.Document(io.BytesIO(raw))
        parts = [p.text for p in d.paragraphs if p.text.strip()]
        for tbl in d.tables:
            for row in tbl.rows:
                cells = [c.text.strip() for c in row.cells]
                if any(cells):
                    parts.append(" | ".join(cells))
        return "\n".join(parts)
    except Exception as e:  # noqa: BLE001
        return f"(无法解析 Word 文档: {e})"


def _extract_xlsx(raw):
    try:
        import io, openpyxl  # noqa: PLC0415
        wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
        out = []
        for ws in wb.worksheets:
            out.append(f"## 工作表: {ws.title}")
            for row in ws.iter_rows(values_only=True):
                vals = ["" if v is None else str(v) for v in row]
                if any(v.strip() for v in vals):
                    out.append(" | ".join(vals))
        return "\n".join(out)
    except Exception as e:  # noqa: BLE001
        return f"(无法解析 Excel 表格: {e})"


def msg_to_anthropic(m):
    """Convert a frontend message {role, content, attachments?} into Anthropic
    format — text stays a string; with attachments it becomes a content-block
    list (image / pdf document / extracted-text)."""
    role = m.get("role", "user")
    text = m.get("content", "") or ""
    atts = m.get("attachments") or []
    if not atts:
        return {"role": role, "content": text}
    blocks = []
    if text:
        blocks.append({"type": "text", "text": text})
    for a in atts:
        name = a.get("name", "file")
        mime = a.get("mime", "")
        data = a.get("data", "")     # base64, no data: prefix
        kind = a.get("kind", "")
        try:
            if kind == "image" and mime in IMAGE_MIMES:
                blocks.append({"type": "image", "source": {
                    "type": "base64", "media_type": mime, "data": data}})
            elif kind == "pdf" or mime == "application/pdf":
                blocks.append({"type": "document", "source": {
                    "type": "base64", "media_type": "application/pdf", "data": data}})
            elif kind in ("docx", "xlsx", "text"):
                import base64  # noqa: PLC0415
                raw = base64.b64decode(data)
                if kind == "docx":
                    txt = _extract_docx(raw)
                elif kind == "xlsx":
                    txt = _extract_xlsx(raw)
                else:
                    txt = raw.decode("utf-8", "ignore")
                blocks.append({"type": "text", "text": f"【附件：{name}】\n{txt[:60000]}"})
            else:
                blocks.append({"type": "text", "text": f"【附件：{name}（暂不支持的类型 {mime}）】"})
        except Exception as e:  # noqa: BLE001
            blocks.append({"type": "text", "text": f"【附件 {name} 处理失败：{e}】"})
    return {"role": role, "content": blocks or text}


@app.route("/api/recommend", methods=["POST"])
def api_recommend():
    """Given the user's question, recommend up to 3 relevant workbench skills."""
    data = request.get_json(force=True)
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"suggestions": []})
    cat = build_catalog()
    lines, index = [], {}
    for m in cat:
        for s in m["skills"]:
            key = f"{m['id']}/skill/{s['name']}"
            index[key] = {"plugin": m["id"], "kind": "skill", "name": s["name"],
                          "label": s["name"], "module": m["title"]}
            lines.append(f"{key} :: {s.get('description_zh') or s.get('description','')}")
        for c in m["commands"]:
            key = f"{m['id']}/command/{c['name']}"
            index[key] = {"plugin": m["id"], "kind": "command", "name": c["name"],
                          "label": "/" + c["name"], "module": m["title"]}
            lines.append(f"{key} :: {c.get('description_zh') or c.get('description','')}")
    sys_prompt = (
        "你是锐明 PM 工作台的技能推荐器。下面是工作台所有可用技能/命令清单，每行格式 `key :: 中文说明`。\n"
        "根据用户的问题，挑选最多 3 个最相关、最可能帮到用户的技能。只能从清单里选，必须原样返回 key。\n"
        "用 JSON 数组返回，每项 {\"key\":\"...\",\"reason\":\"一句话中文说明为什么相关\"}。"
        "若都不相关返回 []。只输出 JSON，不要其它文字。\n\n【技能清单】\n" + "\n".join(lines))
    arr = []
    try:
        client = get_client()
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=700,
            system=sys_prompt, messages=[{"role": "user", "content": question}])
        txt = "".join(getattr(b, "text", "") for b in resp.content)
        mj = re.search(r"\[.*\]", txt, re.S)
        arr = json.loads(mj.group(0)) if mj else []
    except Exception:  # noqa: BLE001
        arr = []
    out = []
    for it in arr:
        k = it.get("key", "")
        if k in index:
            d = dict(index[k])
            d["reason"] = it.get("reason", "")
            out.append(d)
    return jsonify({"suggestions": out[:3]})


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(force=True)
    messages = [msg_to_anthropic(m) for m in data.get("messages", [])]
    model = data.get("model", DEFAULT_MODEL)
    if model not in MODELS:
        model = DEFAULT_MODEL

    skill_body, skill_label = None, None
    sk = data.get("skill")
    if sk and sk.get("name"):
        skill_label = sk.get("label") or sk.get("name")
        skill_body = load_skill_body(sk.get("plugin", ""),
                                     sk.get("kind", "skill"), sk.get("name", ""))

    system = build_system(skill_body, skill_label)

    def generate():
        try:
            client = get_client()
            with client.messages.stream(
                model=model,
                max_tokens=4096,
                system=system,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    yield f"data: {json.dumps({'delta': text})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:  # noqa: BLE001
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    print("锐明 PM 工作台 →  http://127.0.0.1:7860")
    app.run(host="127.0.0.1", port=7860, debug=False, threaded=True)
