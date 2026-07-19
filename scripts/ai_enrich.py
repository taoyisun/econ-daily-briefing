#!/usr/bin/env python3
"""可选 AI 加工:给论文/工作论文补中文翻译 + 按研究方向做相关性分级。

调用优先级:
  1. `claude` CLI(本地已登录,或 CI 中设置 CLAUDE_CODE_OAUTH_TOKEN —— 走订阅额度,不产生 API 账单)
  2. 都不可用则直接退出(网站退化为关键词打分,不影响使用)
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data.json"
import os
BATCH = int(os.environ.get("AI_BATCH", 12))          # 每次调用翻译的条数
MAX_BATCHES = int(os.environ.get("AI_MAX_BATCHES", 5))  # 每次运行最多调用次数(控制额度消耗)

PROFILE = """研究者背景:农业经济学博士生,应用微观经济学/因果推断方向。
核心研究主题:赌博政策(video draw poker、casino、lottery)对破产/家庭财务困境的影响。

分级标准:
- high: 赌博/博彩、破产/债务减免、消费者信贷/家庭债务/财务困境、发薪日贷款等直接相关主题
- medium: 公共经济学(税收、转移支付、社会保险)、城市/区域经济学、
  或方法论上有价值的面板因果推断应用(DiD、事件研究、合成控制、断点回归)
- low: 其余"""


def call_claude(prompt: str) -> str:
    exe = shutil.which("claude")
    if not exe:
        print("[ai] 未找到 claude CLI,跳过 AI 加工")
        sys.exit(0)
    r = subprocess.run(
        [exe, "-p", "--model", "haiku", prompt],
        capture_output=True, text=True, timeout=600,
    )
    if r.returncode != 0:
        raise RuntimeError(f"claude CLI 失败: {r.stderr[:500]}")
    return r.stdout


def parse_json_array(text: str):
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        raise ValueError("输出中未找到 JSON 数组")
    return json.loads(m.group(0))


def enrich_batch(items):
    payload = [
        {"i": idx, "title": it["title"], "abstract": (it.get("abstract") or "")[:1200]}
        for idx, it in enumerate(items)
    ]
    prompt = f"""{PROFILE}

下面是若干篇经济学论文的标题和摘要(JSON)。对每一篇:
1. title_zh: 标题的准确中文翻译
2. abstract_zh: 用 2-3 句中文概括摘要(说明研究问题、识别策略/方法、主要发现;摘要为空则留空字符串)
3. ai_relevance: 按上述研究者背景分级,取 "high"/"medium"/"low"
4. ai_reason: 一句话中文说明分级理由

只输出 JSON 数组,格式: [{{"i":0,"title_zh":"...","abstract_zh":"...","ai_relevance":"...","ai_reason":"..."}}, ...]
不要输出任何其他文字。

论文列表:
{json.dumps(payload, ensure_ascii=False)}"""
    out = parse_json_array(call_claude(prompt))
    for row in out:
        it = items[row["i"]]
        it["title_zh"] = row.get("title_zh", "")
        it["abstract_zh"] = row.get("abstract_zh", "")
        if row.get("ai_relevance") in ("high", "medium", "low"):
            it["ai_relevance"] = row["ai_relevance"]
            it["ai_reason"] = row.get("ai_reason", "")


def main():
    data = json.loads(DATA.read_text())
    # 待处理:还没有中文翻译的论文/工作论文,高相关优先
    pending = [it for key in ("papers", "working_papers") for it in data[key]
               if not it.get("title_zh")]
    pending.sort(key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x.get("relevance"), 2))
    if not pending:
        print("[ai] 无待处理条目")
        return

    done = 0
    for b in range(min(MAX_BATCHES, (len(pending) + BATCH - 1) // BATCH)):
        batch = pending[b * BATCH:(b + 1) * BATCH]
        try:
            enrich_batch(batch)
            done += len(batch)
            print(f"[ai] batch {b + 1}: 完成 {len(batch)} 条")
        except Exception as exc:
            print(f"[ai] batch {b + 1} 失败: {exc}")
            break

    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print(f"[ai] 共处理 {done} 条,剩余 {len(pending) - done} 条留待下次")


if __name__ == "__main__":
    main()
