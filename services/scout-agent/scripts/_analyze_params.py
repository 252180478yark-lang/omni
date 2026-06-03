"""分析三平台 catalog 的参数空间：每个 param key 在各端点用过哪些值 → 看出可切维度 + 取值词表。

目的：参数化迭代前先搞清「哪些参数是可切维度(时间/5A分层/渠道/排序/索引…)、各有哪些取值」，
不瞎试。只读 catalog，不发请求。
"""
import json
from collections import defaultdict, Counter
from pathlib import Path

CAT = Path("/app/catalog")

# 固定上下文（不当维度切，来自 context.json）
FIXED = {"shop_id", "aadvid", "brand_id", "advertiser_id", "industry_id", "app_id",
         "_signature", "msToken", "verifyFp", "fp"}


def is_placeholder(v):
    return isinstance(v, str) and v.startswith("{") and v.endswith("}")


for plat in ("yuntu", "compass", "doudian"):
    f = CAT / f"{plat}.json"
    if not f.exists():
        continue
    entries = json.loads(f.read_text("utf-8"))
    key_vals = defaultdict(Counter)         # param_key -> Counter(value)
    key_eps = defaultdict(set)              # param_key -> set(endpoint keys)
    placeholder_keys = set()
    for e in entries:
        params = e.get("params") or {}
        for k, v in params.items():
            key_eps[k].add(e["key"])
            if is_placeholder(v):
                placeholder_keys.add(k)
                key_vals[k]["<占位:" + v + ">"] += 1
            else:
                key_vals[k][repr(v)] += 1
    print(f"\n========== {plat}（{len(entries)} 端点）==========")
    # 按"被多少端点用到"排序，越通用的越靠前
    for k in sorted(key_vals, key=lambda x: -len(key_eps[x])):
        if k in FIXED:
            continue
        vals = key_vals[k]
        n_ep = len(key_eps[k])
        # 只列出现在 >=2 个端点 或 取值多样(>=2 种) 的参数（潜在可切维度）
        if n_ep < 2 and len(vals) < 2:
            continue
        top = ", ".join(f"{val}×{cnt}" for val, cnt in vals.most_common(8))
        flag = " [日期占位]" if k in placeholder_keys else (" [多值可切]" if len(vals) >= 2 else "")
        print(f"  {k}（{n_ep}端点{flag}）: {top}")
