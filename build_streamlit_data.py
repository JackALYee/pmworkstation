#!/usr/bin/env python3
"""Build a self-contained data bundle for the Streamlit Community Cloud deploy.

Reads from the external source dirs (pm-skills, streamax-knowledge, terminology_db,
product images) via server.py's loaders, and writes everything the Streamlit app
needs into ./streamlit_data/ so the deployed repo has no external path deps.

Run locally whenever skills / knowledge / products change:
    ./.venv/bin/python build_streamlit_data.py
"""
import json
import shutil
from pathlib import Path

from PIL import Image

import server  # reuse all the loaders/parsers

HERE = Path(__file__).resolve().parent
OUT = HERE / "streamlit_data"
(OUT / "products").mkdir(parents=True, exist_ok=True)

# ── catalog + every skill/command body ──────────────────────────────────────
catalog = server.build_catalog()
bodies = {}
for m in catalog:
    for s in m["skills"]:
        bodies[f"{m['id']}/skill/{s['name']}"] = server.load_skill_body(m["id"], "skill", s["name"]) or ""
    for c in m["commands"]:
        bodies[f"{m['id']}/command/{c['name']}"] = server.load_skill_body(m["id"], "command", c["name"]) or ""
(OUT / "pmskills.json").write_text(
    json.dumps({"modules": catalog, "bodies": bodies}, ensure_ascii=False), encoding="utf-8")
print(f"  pmskills.json: {len(catalog)} modules, {len(bodies)} bodies")

# ── always-on system knowledge (persona + streamax knowledge + streamaxpedia) ─
knowledge = "# 锐明产品与销售知识库（始终生效）\n\n" + server.load_streamax_block()
pedia_block = server.build_pedia_block()
if pedia_block:
    knowledge += "\n\n" + pedia_block
(OUT / "system_knowledge.md").write_text(knowledge, encoding="utf-8")
(OUT / "persona.txt").write_text(server.PERSONA, encoding="utf-8")
print(f"  system_knowledge.md: {len(knowledge)} chars")

# ── streamaxpedia (cleaned descriptions + download links) ────────────────────
rows = server.load_streamaxpedia()
peditems = [{
    "term": e.get("term", ""), "category": e.get("category", ""),
    "desc": server.html_to_text(e.get("desc", "")), "files": e.get("files", []) or [],
} for e in rows]
cats = sorted({r["category"] for r in peditems if r["category"]})
(OUT / "streamaxpedia.json").write_text(
    json.dumps({"products": peditems, "categories": cats}, ensure_ascii=False), encoding="utf-8")
print(f"  streamaxpedia.json: {len(peditems)} SKUs, {len(cats)} categories")

# ── product gallery images (downscaled to keep the bundle small) ─────────────
products = []
src_dir = server.PRODUCT_IMAGES
for p in server.list_products():
    cand = [src_dir / f"{p['id']}.jpg", src_dir / f"{p['id']}.png"]
    src = next((c for c in cand if c.exists()), None)
    if not src:
        continue
    try:
        img = Image.open(src).convert("RGB")
        img.thumbnail((400, 400))
        img.save(OUT / "products" / f"{p['id']}.jpg", "JPEG", quality=82)
        products.append({"id": p["id"], "title": p["title"], "file": f"{p['id']}.jpg"})
    except Exception as e:  # noqa: BLE001
        print("  ! image skip", p["id"], e)
(OUT / "products.json").write_text(json.dumps({"products": products}, ensure_ascii=False), encoding="utf-8")
print(f"  products: {len(products)} images")

# ── mascot + models ─────────────────────────────────────────────────────────
shutil.copy(HERE / "assets" / "mascot.png", OUT / "mascot.png")
(OUT / "models.json").write_text(
    json.dumps({"models": server.MODELS, "default": server.DEFAULT_MODEL}, ensure_ascii=False), encoding="utf-8")

print("✓ bundle written to", OUT)
