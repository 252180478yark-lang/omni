"""把 sweep 报告的真实 verdict 应用回 catalog 的 verified 标，并出一份汇总。

verified = (verdict ∈ PASS/PASS_NODATA)；verified_at = sweep 日期。
非 PASS 的归类进 notes，便于后续按类修。
用法：python scripts/apply_sweep.py <date>   (默认今天)
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

CAT = Path(__file__).resolve().parents[1] / "catalog"


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    grand = {}
    for platform in ("yuntu", "compass", "doudian"):
        rep_path = CAT / f"_sweep_{platform}_{d}.json"
        if not rep_path.exists():
            print(f"!! 缺 {rep_path.name}，跳过", flush=True)
            continue
        rep = json.loads(rep_path.read_text("utf-8"))
        verdict_by_key = {r["key"]: r for r in rep["results"]}

        entries = json.loads((CAT / f"{platform}.json").read_text("utf-8"))
        cat_pass = 0
        for e in entries:
            r = verdict_by_key.get(e["key"])
            if not r:
                continue
            v = r["verdict"]
            ok = v in ("PASS", "PASS_NODATA")
            e["verified"] = ok
            e["verified_at"] = d
            if ok:
                cat_pass += 1
                if v == "PASS_NODATA":
                    e["notes"] = "端点健康，业务当前无数据 (sweep PASS_NODATA)"
            else:
                e["notes"] = f"sweep {v} (code={r.get('code')}) @ {d} 待修"
        (CAT / f"{platform}.json").write_text(
            json.dumps(entries, ensure_ascii=False, indent=2), "utf-8")

        counts = Counter(r["verdict"] for r in rep["results"])
        # 按层（原 testcase verified vs inventory 候选）
        tc = [r for r in rep["results"] if r["was_verified"]]
        cand = [r for r in rep["results"] if not r["was_verified"]]
        tc_ok = sum(1 for r in tc if r["verdict"] in ("PASS", "PASS_NODATA"))
        cand_ok = sum(1 for r in cand if r["verdict"] in ("PASS", "PASS_NODATA"))
        grand[platform] = {
            "total": len(entries), "verified_now": cat_pass,
            "testcase_tier": f"{tc_ok}/{len(tc)}",
            "candidate_tier": f"{cand_ok}/{len(cand)}",
            "verdicts": dict(counts),
        }
    print(json.dumps(grand, ensure_ascii=False, indent=2))
    total = sum(g["total"] for g in grand.values())
    ok = sum(g["verified_now"] for g in grand.values())
    print(f"\n== 合计 verified(可用) {ok}/{total} = {100*ok//max(1,total)}% ==")


if __name__ == "__main__":
    main()
