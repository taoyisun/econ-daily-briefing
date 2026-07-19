# 每日学术简报 · Econ Daily Briefing

个人定制的每日学术聚合站:期刊论文(Top-5 / 公共经济 / 城市)、NBER 工作论文、
赌博与破产政策新闻、政策报告(CFPB / GAO / US Courts / 智库)、会议截止日期。

## 架构

- `scripts/build.py` — 抓取 CrossRef + RSS,关键词打分,写 `docs/data.json`
- `scripts/ai_enrich.py` — 可选:调用 Claude(订阅额度)做中文翻译 + 相关性分级
- `site/` — 静态前端(构建时复制到 `docs/`),GitHub Pages 从 `docs/` 目录发布
- `.github/workflows/daily.yml` — 每天 UTC 11:00 自动更新
- `config.yml` — 期刊、RSS 源、关键词都在这里改
- `conferences.yml` — 会议截止日期,手动维护

## 本地运行

```bash
python3 -m venv .venv && .venv/bin/pip install requests feedparser pyyaml
.venv/bin/python scripts/build.py
.venv/bin/python scripts/ai_enrich.py   # 可选,需要本地 claude CLI 已登录
open docs/index.html                     # 或 python3 -m http.server -d docs
```

## 启用 CI 中的 AI 翻译(不产生 API 账单)

1. 本地运行 `claude setup-token`,得到 `sk-ant-oat01-...` token
2. 仓库 Settings → Secrets and variables → Actions → 新建 secret `CLAUDE_CODE_OAUTH_TOKEN`
3. 之后每日运行会自动翻译新论文并按研究方向分级
