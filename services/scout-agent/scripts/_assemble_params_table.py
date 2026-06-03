"""把 params-survey-to-table workflow 的三平台维度卡合成一份桌面总表。host python 跑。"""
import json
import sys
from pathlib import Path

SRC = Path(sys.argv[1])
OUT = Path(r"C:\Users\Administrator\Desktop\项目现状和蓝图\三平台维度全展开表-2026-06-03.md")

d = json.loads(SRC.read_text(encoding="utf-8"))
r = d["result"]
P = []
P.append("# 三平台维度全展开表 · 2026-06-03（参数化迭代版）\n\n")
P.append("> 这次每个端点**切了多个维度**(指标 index_selected / 时间窗 / per-SKU / 排序 / card / benchmark / tab …)，\n")
P.append("> 共跑出 **940 个真实数据切面**(yuntu 224 / compass 616 / doudian 100)。下表按端点给「维度卡」：\n")
P.append("> **默认给啥 + 能切哪些维度 + 每维度给啥真数 + 样例值**。所有样例值摘自真实返回。\n")
P.append("> **用法：你勾哪些端点(及它的哪些维度)进 Power BI，我给勾中的建落库桥。**\n\n")
P.append("## 🎯 各平台最值得进 Power BI 的端点（subagent 推荐）\n\n")
for plat, cn in [("compass", "罗盘"), ("doudian", "抖店"), ("yuntu", "云图")]:
    blk = r.get(plat, {})
    P.append(f"### {cn}（{plat}）\n")
    for tp in (blk.get("top_picks") or []):
        P.append(f"- {tp}\n")
    P.append("\n")
P.append("\n---\n\n# 完整维度卡（按平台 × 业务域 × 端点）\n\n")
for plat in ("compass", "doudian", "yuntu"):
    P.append(r.get(plat, {}).get("report_md", "(无)"))
    P.append("\n\n---\n\n")
txt = "".join(P)
OUT.write_text(txt, encoding="utf-8")
print(f"wrote {OUT}  ({len(txt)} chars)")
