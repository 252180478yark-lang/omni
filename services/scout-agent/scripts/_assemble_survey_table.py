"""把 survey-to-table workflow 的三平台 report_md 合成一份桌面总表。host python 跑。"""
import json
import sys
from pathlib import Path

SRC = Path(sys.argv[1])
OUT = Path(r"C:\Users\Administrator\Desktop\项目现状和蓝图\三平台可取真实数据总表-2026-06-03.md")

d = json.loads(SRC.read_text(encoding="utf-8"))
r = d["result"]
P = []
P.append("# 三平台可取真实数据总表 · 2026-06-03\n\n")
P.append("> survey 全部 491 端点 · 189 PASS · **144 有真实数据** · 45 端点通但今日无数据(PASS_NODATA)。\n")
P.append("> 三平台已登录(cookie 在 sessions/)。下表样例值均摘自各端点**真实返回**。\n")
P.append("> **用法：你勾哪些进 Power BI(分析面)，我给勾中的逐个建落库桥(那时定口径)。**\n\n")
P.append("## 🎯 各平台最值得进 Power BI 的核心端点（agent 推荐）\n\n")
for plat, cn in [("yuntu", "云图"), ("compass", "罗盘"), ("doudian", "抖店")]:
    blk = r.get(plat, {})
    P.append(f"### {cn}（{plat}） · {blk.get('endpoint_count', '?')} 端点有数据\n")
    for tp in (blk.get("top_picks") or []):
        P.append(f"- {tp}\n")
    P.append("\n")
P.append("\n---\n\n# 完整可取指标表（按平台 × 业务域）\n\n")
for plat in ("yuntu", "compass", "doudian"):
    P.append(r.get(plat, {}).get("report_md", "(无)"))
    P.append("\n\n---\n\n")
txt = "".join(P)
OUT.write_text(txt, encoding="utf-8")
print(f"wrote {OUT}  ({len(txt)} chars)")
