#!/usr/bin/env python3
"""每日简报构建脚本:抓取所有数据源 -> 打分 -> 合并历史 -> 写 docs/data.json"""
import html
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = yaml.safe_load((ROOT / "config.yml").read_text())
UA = {"User-Agent": "econ-daily-briefing (mailto:%s)" % CONFIG["crossref_mailto"]}
NOW = datetime.now(timezone.utc)


def log(msg):
    print(f"[build] {msg}", flush=True)


def clean_text(s):
    """去掉 JATS/HTML 标签并解码实体"""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def score_relevance(text):
    """关键词打分:返回 (level, [matched topic labels])"""
    text_l = text.lower()
    matched, level = [], "low"
    for topic in CONFIG["relevance_topics"].values():
        if any(k.lower() in text_l for k in topic["keywords"]):
            matched.append(topic["label"])
            if topic["level"] == "high":
                level = "high"
            elif topic["level"] == "medium" and level != "high":
                level = "medium"
    return level, matched


def entry_date(e):
    for key in ("published_parsed", "updated_parsed"):
        t = e.get(key)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


# ---------------- 期刊论文 (CrossRef) ----------------

def fetch_journal_papers():
    since = (NOW - timedelta(days=CONFIG["lookback_days"])).strftime("%Y-%m-%d")
    papers = []
    for j in CONFIG["journals"]:
        url = (f"https://api.crossref.org/journals/{j['issn']}/works"
               f"?filter=from-created-date:{since},type:journal-article"
               f"&rows=50&sort=created&order=desc&mailto={CONFIG['crossref_mailto']}")
        try:
            r = requests.get(url, headers=UA, timeout=30)
            r.raise_for_status()
            items = r.json()["message"]["items"]
        except Exception as exc:
            log(f"CrossRef {j['name']} 失败: {exc}")
            continue
        for it in items:
            title = clean_text(" ".join(it.get("title") or []))
            if not title:
                continue
            authors = ", ".join(
                " ".join(filter(None, [a.get("given"), a.get("family")]))
                for a in it.get("author", [])) or ""
            abstract = clean_text(it.get("abstract", ""))
            created = (it.get("created") or {}).get("date-time", "")
            level, tags = score_relevance(f"{title} {abstract}")
            papers.append({
                "id": it.get("DOI", title),
                "title": title,
                "authors": authors,
                "journal": j["name"],
                "tier": j["tier"],
                "doi": it.get("DOI", ""),
                "url": it.get("URL", ""),
                "abstract": abstract[:2500],
                "published": created,
                "relevance": level,
                "topics": tags,
            })
        log(f"CrossRef {j['name']}: {len(items)} items")
    return papers


# ---------------- 工作论文 ----------------

def fetch_working_papers():
    wps = []
    for feed in CONFIG["working_paper_feeds"]:
        f = feedparser.parse(requests.get(feed["url"], headers=UA, timeout=30).content)
        for e in f.entries[: CONFIG["max_items_per_feed"] * 2]:
            title = clean_text(e.get("title", ""))
            summary = clean_text(e.get("summary", ""))[:2500]
            d = entry_date(e)
            level, tags = score_relevance(f"{title} {summary}")
            wps.append({
                "id": e.get("link", title),
                "title": title,
                "authors": clean_text(e.get("author", "")),
                "source": feed["name"],
                "url": e.get("link", ""),
                "abstract": summary,
                "published": d.isoformat() if d else "",
                "relevance": level,
                "topics": tags,
            })
        log(f"WP {feed['name']}: {len(f.entries)} items")
    return wps


# ---------------- 新闻 / 报告 ----------------

def fetch_feed_items(feeds, lookback_days):
    cutoff = NOW - timedelta(days=lookback_days)
    out = []
    for feed in feeds:
        try:
            f = feedparser.parse(requests.get(feed["url"], headers=UA, timeout=30).content)
        except Exception as exc:
            log(f"feed {feed['name']} 失败: {exc}")
            continue
        n = 0
        for e in f.entries:
            d = entry_date(e)
            if d and d < cutoff:
                continue
            title = clean_text(e.get("title", ""))
            if not title:
                continue
            level, tags = score_relevance(title + " " + clean_text(e.get("summary", ""))[:500])
            out.append({
                "id": e.get("link", title),
                "title": title,
                "source": feed["name"],
                "category": feed.get("category", ""),
                "url": e.get("link", ""),
                "summary": clean_text(e.get("summary", ""))[:600],
                "published": d.isoformat() if d else "",
                "relevance": level,
                "topics": tags,
            })
            n += 1
            if n >= CONFIG["max_items_per_feed"]:
                break
        log(f"feed {feed['name']}: kept {n}")
    return out


# ---------------- 会议 ----------------

def load_conferences():
    path = ROOT / "conferences.yml"
    if not path.exists():
        return []
    return yaml.safe_load(path.read_text()) or []


# ---------------- 合并历史(保留 AI 翻译结果) ----------------

def merge_with_previous(new_items, old_items, keep_days):
    """按 id 合并;旧条目里的 title_zh/abstract_zh/ai_* 字段带到新条目"""
    old_by_id = {it["id"]: it for it in old_items}
    cutoff = (NOW - timedelta(days=keep_days)).isoformat()
    merged = {}
    for it in new_items:
        prev = old_by_id.get(it["id"], {})
        for k in ("title_zh", "abstract_zh", "ai_relevance", "ai_reason"):
            if prev.get(k):
                it[k] = prev[k]
        merged[it["id"]] = it
    # 保留窗口内但本次没抓到的旧条目(RSS 滚动出窗)
    for it in old_items:
        if it["id"] not in merged and (it.get("published") or "9999") >= cutoff:
            merged[it["id"]] = it
    items = sorted(merged.values(), key=lambda x: x.get("published", ""), reverse=True)
    return items


def main():
    out_path = ROOT / "docs" / "data.json"
    old = {}
    if out_path.exists():
        old = json.loads(out_path.read_text())

    data = {
        "generated_at": NOW.isoformat(),
        "papers": merge_with_previous(fetch_journal_papers(), old.get("papers", []),
                                      CONFIG["lookback_days"] + 15),
        "working_papers": merge_with_previous(fetch_working_papers(), old.get("working_papers", []), 60),
        "news": merge_with_previous(
            fetch_feed_items(CONFIG["news_feeds"], CONFIG["news_lookback_days"]),
            old.get("news", []), CONFIG["news_lookback_days"]),
        "reports": merge_with_previous(
            fetch_feed_items(CONFIG["report_feeds"], 30), old.get("reports", []), 45),
        "conferences": load_conferences(),
    }

    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    log(f"写入 {out_path}: papers={len(data['papers'])} wp={len(data['working_papers'])} "
        f"news={len(data['news'])} reports={len(data['reports'])}")

    # 把静态站文件同步到 docs/
    import shutil
    for f in (ROOT / "site").iterdir():
        shutil.copy(f, ROOT / "docs" / f.name)


if __name__ == "__main__":
    sys.exit(main())
