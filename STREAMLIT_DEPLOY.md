# 部署到 Streamlit Community Cloud

本目录现在同时支持两种运行方式：

| 运行方式 | 入口 | 用途 |
|---|---|---|
| 本地 Flask（密钥在服务端） | `./.venv/bin/python server.py` → :7860 | 本地开发，最完整 |
| Streamlit（Community Cloud） | `streamlit run streamlit_app.py` → :8501 | 上线，保留原 UI |

Streamlit 版做法：用 `components.html` 内嵌**完全相同的 UI**（`templates/index.html`），登录后注入 `window.BOOT`（技能库、知识库、产品库、API Key）。页面内的 `fetch` 垫片把 `/api/*` 改为读取 BOOT + **浏览器直连 DeepSeek**（OpenAI 兼容）。DeepSeek 为纯文本模型：Word/Excel/PDF 在浏览器端提取文字（mammoth.js / SheetJS / pdf.js），**图片无法识别**。

> ⚠️ 该模式下 API Key 会在登录后注入浏览器，任何登录的 Streamax 员工都能在开发者工具里看到。请使用**设了用量上限/预算告警**的 Key。

---

## 本地测试

```bash
cd "/Users/jiachenyi/Desktop/Streamax/pmworkstation"
./.venv/bin/python -m streamlit run streamlit_app.py
```
浏览器开 http://localhost:8501 → 用 `test` / `testme` 登录（或真实 @streamax.com 邮箱）。

`.streamlit/secrets.toml` 已在本地生成（含 Key，已 gitignore）。

---

## 你需要手动做的步骤

### 1. 推到 GitHub
```bash
cd "/Users/jiachenyi/Desktop/Streamax/pmworkstation"
git add -A && git commit -m "update"
git push
```
`Deepseek API.md` 和 `.streamlit/secrets.toml` 已被 `.gitignore` 排除，不会上传。

### 2. 在 Streamlit Community Cloud 创建应用
1. 打开 https://share.streamlit.io → **New app**
2. 选刚才的仓库 / 分支 `main` / 主文件 **`streamlit_app.py`**
3. **Advanced settings → Secrets** 粘贴：
   ```toml
   DEEPSEEK_API_KEY = "sk-..."
   ```
4. Deploy。应用地址形如 `https://<app-name>.streamlit.app`

> Community Cloud 出站 SMTP(465) 可用，所以 @streamax.com 邮箱登录能正常工作（与 Jerry GPT 一致）。

### 3. （关于 pm.streamax-smb.com）
Streamlit Community Cloud **不支持真正的自定义域名**。两种现实选择：
- 直接用 `*.streamlit.app` 地址；
- 在 Cloudflare 给 `pm.streamax-smb.com` 建一条**重定向规则** → `https://<app>.streamlit.app`（地址栏最终会显示 streamlit.app）。

如果一定要 `pm.streamax-smb.com` 原样显示且保留本 UI，则需换成自托管（VPS/Fly），那是另一条路。

---

## 更新内容后

技能库 / 锐明知识 / 产品库有更新时，重新打包再提交：
```bash
./.venv/bin/python build_streamlit_data.py
git add -A && git commit -m "refresh data" && git push
```

## 一个待你浏览器验证的点
浏览器直连 DeepSeek 已确认支持 CORS（`api.deepseek.com` 会回传 `access-control-allow-origin`）。部署后请实际发一条消息确认回复正常；若流式被网络拦截会自动回退非流式。CDN（marked / mermaid / mammoth / SheetJS / pdf.js）也需能在 iframe 内加载。
