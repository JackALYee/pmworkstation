# 锐明 PM 工作台 · Streamax PM Workbench

面向锐明产品团队的本地 AI 工作台。把世界级 PM 方法论（9 大模块、68 个技能、42 条工作流命令）与锐明真实产品知识（型号、规格、定价、竞争情报）融合在一个可交互界面里，并内置流式 AI 对话。

## 启动

```bash
cd "/Users/jiachenyi/Desktop/Streamax/pmworkstation"
./.venv/bin/python server.py
```

打开浏览器访问 **http://127.0.0.1:7860**

> 环境在 `.venv` 里（flask + openai 等）。如需重建：
> `python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt`

## 怎么用

1. **首页** — 9 大 PM 能力模块（产品发现 / 战略 / 执行 / 市场研究 / 数据分析 / GTM / 营销增长 / 工具箱 / AI 交付），点进任一模块。
2. **加载技能** — 在模块里点「加载到对话」，该方法论（SKILL.md / 命令）即作为本次对话的工作框架，AI 会严格按其步骤推进。
3. **自由对话** — 也可不加载技能直接提问。无论是否加载，**所有回答都内置锐明产品知识**。
4. **产品库** — 点任一产品图，AI 结合该型号规格 / 定价 / 卖点展开。
5. **模型切换** — 右上角可选 DeepSeek V3（默认，通用）/ DeepSeek R1（推理）。

## 架构

- `server.py` — Flask 后端：托管界面、代理 DeepSeek API（**密钥仅在服务端**，读取自环境变量 `DEEPSEEK_API_KEY` 或 `Deepseek API.md`）、实时从磁盘读取技能库与锐明知识。
- `templates/index.html` — 单文件前端（原生 JS + marked 渲染 Markdown，SSE 流式）。
- `i18n_zh.json` — 技能/命令解释的中文译文（界面显示中文，卡片右上角 `?` 悬浮显示英文原注释）。
- 数据源（实时读取，改了即生效，无需重启重建）：
  - PM 技能库：`/Users/jiachenyi/Documents/AI Skill/pm-skills`
  - 锐明知识（始终注入、带缓存）：`…/auto email/.claude/skills/streamax-knowledge`（SKILL.md + reference/）
  - 技术规格书库（Streamaxpedia，与 Jerry GPT 共用）：`…/salestoolkit/terminology_db.py` —— 115 个型号 + 规格书/用户手册下载链接，注入 AI 上下文并在「锐明产品库」展示可下载链接
  - 产品图：`…/salestoolkit/assets/products`

## 接口

| 路由 | 说明 |
|---|---|
| `GET /api/catalog` | 9 模块 + 技能/命令清单 |
| `GET /api/skill?plugin=&kind=&name=` | 单个技能/命令正文 |
| `GET /api/products` | 产品库图片清单 |
| `POST /api/chat` | 流式对话（SSE），可带 `skill` 与 `model` |

## 安全提示

`Deepseek API.md` / `.streamlit/secrets.toml` 含明文 API Key（均已 gitignore）。注意：Streamlit Cloud 版会在登录后把 Key 注入浏览器，请用设了用量上限的 Key。
