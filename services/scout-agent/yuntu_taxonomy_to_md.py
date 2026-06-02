"""把 data/yuntu_audience_taxonomy_v1.json 渲染成 markdown 字典文档。

输出到 data/yuntu_audience_taxonomy_v1.md 以便后续入 KB。

跑法：
    cd E:\\agent\\omni\\services\\scout-agent
    python yuntu_taxonomy_to_md.py
"""
import json
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_IN = REPO_ROOT / "data" / "yuntu_audience_taxonomy_v1.json"
DATA_OUT = REPO_ROOT / "data" / "yuntu_audience_taxonomy_v1.md"


CN_NUMS = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二"]


def clean_options(options: list[str], item_name: str = "") -> list[str]:
    """清掉常见噪声 + 去重 + 切多行 + 拆数字尾巴（如"时尚\\n8.6亿"）。"""
    import re

    noise = {
        "详情查看", "标签帮助文档", "预计覆盖人数", "点击预估",
        "取消", "确定", "请选择", "全选", "清空", "搜索", "已选0项",
        "暂无数据", "请输入搜索词", "已选", "兴趣分类", "兴趣标签是必填字段",
        "已选0个", "兴趣标签", "8大消费群体", "标签",
    }
    # 数字尾巴模式（如 "时尚\n8.6亿" → "时尚"）
    num_tail = re.compile(r"^([^\d\s\n]+?)\s*\n[\d.]+[万亿千]?$")

    seen = set()
    out = []
    for opt in options:
        opt = (opt or "").strip()
        if not opt:
            continue
        # 切多行（每个 \n 后取首段）
        if "\n" in opt:
            m = num_tail.match(opt)
            if m:
                opt = m.group(1).strip()
            else:
                # 取第一行
                opt = opt.split("\n")[0].strip()
        if not opt:
            continue
        # 粗过滤
        if opt in noise:
            continue
        if opt == item_name:
            continue
        if any(opt.startswith(p) for p in ["注：", "注意：", "推荐选择", "时间跨度", "0/", "/100"]):
            continue
        # 纯数字（不含字母/汉字/连字符）行
        if re.match(r"^[\d./]+$", opt):
            continue
        # 重复去重
        if opt in seen:
            continue
        seen.add(opt)
        out.append(opt)
    return out


def render(data: dict) -> str:
    lines = []
    scraped_at = data.get("scraped_at", "")
    if scraped_at:
        try:
            dt = datetime.fromisoformat(scraped_at.replace("Z", "+00:00"))
            scraped_human = dt.strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            scraped_human = scraped_at
    else:
        scraped_human = "unknown"

    lines.append("# 巨量云图 自定义人群创建页 完整标签字典 v1")
    lines.append("")
    lines.append("> **抓取时间**：" + scraped_human)
    lines.append("> **来源**：" + data.get("url", ""))
    lines.append("> **用途**：LLM 出圈包 SOP 时的标签字典 ground truth，禁止虚构二三级标签")
    lines.append("")
    lines.append("> **结构**：")
    lines.append("> - 一级 = 6 个维度（我的人群 / 触点场景圈人 / 用户属性 / 兴趣偏好 / 行业品类兴趣 / 标签工厂）")
    lines.append("> - 二级 = 分组（如 基础属性 / 地域属性）")
    lines.append("> - 三级 = 标签项（如 八大消费群体 / IP偏好），点击它在云图后台弹出选项")
    lines.append("> - 四级 = 弹窗内具体可选项（如 IP偏好 → 明星偏好/电影偏好/电视剧偏好/综艺偏好/动漫偏好）")
    lines.append("")

    # 一级目录
    lines.append("## 总览")
    lines.append("")
    for i, dim in enumerate(data.get("dimensions", [])):
        nb = sum(len(g.get("sub_items", [])) for g in dim.get("groups", []))
        lines.append(f"- **{dim['name']}**（{len(dim.get('groups', []))} 个二级分组 / {nb} 个三级标签）")
    lines.append("")

    # 一级一级展开
    for di, dim in enumerate(data.get("dimensions", [])):
        cn_num = CN_NUMS[di] if di < len(CN_NUMS) else str(di + 1)
        lines.append(f"## {cn_num}、{dim['name']}")
        lines.append("")
        for grp in dim.get("groups", []):
            grp_name = grp.get("name") or "（未命名分组）"
            lines.append(f"### {grp_name}")
            lines.append("")
            for it in grp.get("sub_items", []):
                lines.append(f"#### {it['name']}")
                lines.append("")
                opts = clean_options(it.get("options", []), it.get("name", ""))
                if opts:
                    for o in opts:
                        lines.append(f"- {o}")
                else:
                    lines.append(f"- _未抓到选项（弹窗为输入框/上传/无固定选项）_")
                # struct 详细信息（如果 cascader_top 有内容，附带显示）
                struct = it.get("options_struct", {})
                cas = struct.get("cascader_top") or []
                if cas:
                    for c in cas:
                        ct = c.get("column_title", "").strip()
                        items = c.get("items", []) or []
                        # 同样的清洗逻辑
                        cleaned = clean_options(items, item_name=ct)
                        if cleaned:
                            label = ct or "（级联首列示例）"
                            preview = cleaned[:30]
                            note = ""
                            if len(cleaned) > 30:
                                note = f"（前 30 个，云图后台还有更多虚拟滚动加载）"
                            elif len(cleaned) == 30:
                                note = f"（云图后台 ReactVirtualized 渲染上限，可能更多）"
                            lines.append("")
                            lines.append(f"  **{label}**{note}：")
                            for o in preview:
                                lines.append(f"  - {o}")
                lines.append("")
        lines.append("")

    # 附录：使用说明
    lines.append("## 使用约束（给 LLM）")
    lines.append("")
    lines.append("1. **禁止虚构**：圈包 SOP 出建议时，所有二三级标签必须从本字典选择。如果业务需要的标签本字典没有，必须在 SOP 里明示「云图后台无对应标签，建议用 X 替代」，不允许凭空想象。")
    lines.append("2. **粒度匹配**：圈人时优先用四级具体选项（如 IP偏好 → 明星偏好），不要只停在三级标签名（IP偏好）。")
    lines.append("3. **同义词警告**：本字典中的官方命名是唯一权威，例如「八大消费群体」（不是「八类消费人群」）、「Z世代」（不是「90后/00后」）、「精致妈妈」（不是「都市妈妈」）。")
    lines.append("4. **覆盖维度**：圈包 SOP 至少覆盖 3 个维度交叉（如 用户属性 × 兴趣偏好 × 行业品类兴趣）。")
    lines.append("5. **更新提示**：本字典抓取时间见文档头，云图后台标签每月可能微调，季度重抓一次保持新鲜度。")
    lines.append("")

    return "\n".join(lines)


def main():
    if not DATA_IN.exists():
        print(f"[ERR] {DATA_IN} not found; run dump_yuntu_audience_taxonomy.py first")
        return
    data = json.loads(DATA_IN.read_text(encoding="utf-8"))
    md = render(data)
    DATA_OUT.write_text(md, encoding="utf-8")
    print(f"[OK] {DATA_OUT} ({len(md)} chars, {md.count(chr(10))} lines)")


if __name__ == "__main__":
    main()
