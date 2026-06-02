"""完整抓取巨量云图自定义人群创建页所有二三级标签（W4-B 切片 14.3 phase B+8 D4）。

V2 探索摸清楚的结构：
- 6 个一级维度（按 y 坐标分组）：
  我的人群(~285) / 触点场景圈人(~408-516) / 用户属性(~639-747) /
  兴趣偏好(~870-924) / 行业品类兴趣(~1047-1209) / 标签工厂(~1332)
- 59 个二级标签（class=yuntu_analysis-popper-trigger-click）
- 二级点击后的弹窗结构 3 种：
  A. 直接 cascader（地域分布、八大消费群体...）
  B. 多 radio + cascader（内容偏好 4 模式 / IP 偏好 5 模式）
  C. 小弹窗（预测年龄等，可能是滑块/输入框）

抓取策略：
- 遍历所有 popper-trigger
- 每个点击 → 等 modal → 检测 radio 数 → 分支处理
- 抓完用 ESC 或点取消关弹窗
- 单个二级抓失败不挂全部，记 warning 继续
- 实时写 jsonlines，断了能从最后一行续

跑法（host）：
    cd E:\\agent\\omni\\services\\scout-agent
    python dump_yuntu_audience_taxonomy.py

输出：
    data/yuntu_taxonomy_progress.jsonl  实时进度（断点续跑用）
    data/yuntu_audience_taxonomy_v1.json  完整 JSON 树（end）
    snapshots/_inspect/popups/<二级名>.png  每个弹窗截图
"""
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

URL = "https://yuntu.oceanengine.com/yuntu_brand/ecom/analysis/audience/create?aadvid=1805203190148185"

# 6 个一级维度（按 V2 探索的 y 坐标范围分组）
DIMENSION_Y_RANGES = [
    ("我的人群", 250, 350),
    ("触点场景圈人", 380, 540),
    ("用户属性", 580, 800),
    ("兴趣偏好", 830, 980),
    ("行业品类兴趣", 1010, 1280),
    ("标签工厂", 1300, 1400),
]

# 已知的"分组"（按 y 坐标内分组，V2 raw_text 解析得来）
GROUPS_BY_DIM = {
    "触点场景圈人": [("私域触点", 380, 480), ("公域触点", 490, 540)],
    "用户属性": [("基础属性", 580, 720), ("地域属性", 720, 800)],
    "兴趣偏好": [("内容偏好", 830, 900), ("行为偏好", 900, 980)],
    "行业品类兴趣": [
        ("通用行业人群", 1010, 1080),
        ("细分行业人群", 1080, 1140),
        ("行业特色人群", 1140, 1280),
    ],
}


def detect_dimension(y: float) -> str:
    for name, lo, hi in DIMENSION_Y_RANGES:
        if lo <= y <= hi:
            return name
    return "未知"


def detect_group(dim: str, y: float) -> str:
    if dim not in GROUPS_BY_DIM:
        return dim
    for name, lo, hi in GROUPS_BY_DIM[dim]:
        if lo <= y <= hi:
            return name
    return dim


async def scrape_modal_options(page) -> dict:
    """抓当前打开的弹窗里的所有选项 + 检测 radio 模式。"""
    info = await page.evaluate("""
() => {
  const modal = document.querySelector('[class*="yuntu_analysis-modal-show"], [class*="yuntu_analysis-modal-content-container"]');
  if (!modal) return { has_radio: false, radios: [], options_flat: [], modal_text: '', error: 'no_modal_found' };

  const radios = [];
  modal.querySelectorAll('label').forEach(lb => {
    if (lb.querySelector('input[type="radio"]')) {
      const t = (lb.innerText || '').trim();
      if (t && t.length < 30 && !radios.includes(t)) radios.push(t);
    }
  });

  const opts = [];
  document.querySelectorAll('[class*="yuntu_analysis-cascader-column-list"] [class*="list-item-container-level-1"]').forEach(el => {
    const t = (el.innerText || '').trim();
    if (t && t !== '全选' && !opts.includes(t)) opts.push(t);
  });

  const modal_text = (modal.innerText || '').trim();

  return {
    has_radio: radios.length > 0,
    radios: radios,
    options_flat: opts,
    modal_text: modal_text.slice(0, 800),
  };
}
    """)
    return info


async def click_radio(page, radio_text: str) -> bool:
    """点击 modal 里某个 radio。"""
    try:
        loc = page.locator(f'label:has-text("{radio_text}")').first
        if await loc.count() > 0:
            await loc.click(timeout=3000)
            await asyncio.sleep(0.8)
            return True
    except Exception:
        pass
    return False


async def close_modal(page):
    """关闭弹窗（先 ESC，失败试点取消）。"""
    try:
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.4)
        still = await page.evaluate(
            'document.querySelectorAll("[class*=yuntu_analysis-modal-show]").length'
        )
        if still > 0:
            cancel = page.locator('button:has-text("取消")').first
            if await cancel.count() > 0:
                await cancel.click(timeout=2000)
                await asyncio.sleep(0.4)
    except Exception:
        pass


async def main():
    from playwright.async_api import async_playwright

    out_dir = Path("./data")
    out_dir.mkdir(parents=True, exist_ok=True)
    snap_dir = Path("./snapshots/_inspect/popups")
    snap_dir.mkdir(parents=True, exist_ok=True)

    progress_file = out_dir / "yuntu_taxonomy_progress.jsonl"
    final_json = out_dir / "yuntu_audience_taxonomy_v1.json"

    sess = Path("./sessions/yuntu/user_data")

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(sess),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1920, "height": 1080},
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        print(f"[i] 加载中...")
        await asyncio.sleep(10)

        triggers = await page.evaluate("""
() => {
  const out = [];
  document.querySelectorAll('[class*="yuntu_analysis-popper-trigger-click"]').forEach(el => {
    const text = (el.innerText || '').trim();
    if (!text || text.length > 30) return;
    const r = el.getBoundingClientRect();
    if (r.width < 30 || r.height < 30) return;
    out.push({
      text: text,
      x: Math.round(r.x),
      y: Math.round(r.y),
      w: Math.round(r.width),
    });
  });
  return out;
}
        """)
        print(f"[OK] 抓到 {len(triggers)} 个二级 trigger")
        triggers.sort(key=lambda t: (t["y"], t["x"]))

        # 续跑：跳过已抓的
        done = set()
        if progress_file.exists():
            with progress_file.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                        if rec.get("ok"):
                            done.add(rec.get("name"))
                    except Exception:
                        pass
            if done:
                print(f"[i] 续跑：已成功抓 {len(done)} 个，跳过")

        # 逐个抓
        for i, t in enumerate(triggers):
            name = t["text"]
            if name in done:
                continue
            dim = detect_dimension(t["y"])
            group = detect_group(dim, t["y"])
            print(f"\n[{i+1}/{len(triggers)}] 「{name}」 (dim={dim}, group={group})")

            try:
                loc = page.locator(f'[class*="popper-trigger-click"]:has-text("{name}")').first
                if await loc.count() == 0:
                    raise RuntimeError(f"找不到 trigger")

                await loc.scroll_into_view_if_needed(timeout=3000)
                await asyncio.sleep(0.3)
                await loc.click(timeout=5000)
                await asyncio.sleep(1.5)

                safe_name = re.sub(r"[^一-龥A-Za-z0-9]+", "_", name)[:30]
                png_path = snap_dir / f"{i:02d}_{safe_name}.png"
                try:
                    await page.screenshot(path=str(png_path), full_page=False)
                except Exception:
                    pass

                snap = await scrape_modal_options(page)

                options_by_mode = {}
                if snap.get("has_radio") and snap.get("radios"):
                    for radio in snap["radios"]:
                        ok = await click_radio(page, radio)
                        if ok:
                            sub = await scrape_modal_options(page)
                            options_by_mode[radio] = sub.get("options_flat", [])

                rec = {
                    "ordinal": i,
                    "dim": dim,
                    "group": group,
                    "name": name,
                    "x": t["x"],
                    "y": t["y"],
                    "type": "radio_cascader" if snap.get("has_radio") else (
                        "cascader" if snap.get("options_flat") else "empty_or_unknown"
                    ),
                    "radios": snap.get("radios", []),
                    "options_flat": snap.get("options_flat", []),
                    "options_by_mode": options_by_mode,
                    "modal_text": snap.get("modal_text", "")[:600],
                    "png_path": str(png_path),
                    "ok": True,
                }

                await close_modal(page)
                await asyncio.sleep(0.5)

            except Exception as exc:
                rec = {
                    "ordinal": i,
                    "dim": dim,
                    "group": group,
                    "name": name,
                    "x": t["x"],
                    "y": t["y"],
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                print(f"  [!!] 抓失败: {exc}")
                await close_modal(page)
                await asyncio.sleep(1)

            with progress_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

            if rec.get("ok"):
                n_opts = len(rec.get("options_flat") or [])
                n_modes = len(rec.get("options_by_mode") or {})
                if n_modes > 0:
                    n_total = sum(len(v) for v in rec["options_by_mode"].values())
                    print(f"  ✓ {len(rec['radios'])} radio 模式 / 共 {n_total} 个三级选项")
                else:
                    print(f"  ✓ {n_opts} 个三级选项")

        # 合并 progress 成完整 JSON 树
        all_records = []
        if progress_file.exists():
            with progress_file.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        all_records.append(json.loads(line))
                    except Exception:
                        pass

        tree = {dim: {} for dim, _, _ in DIMENSION_Y_RANGES}
        for r in all_records:
            d = r.get("dim", "未知")
            g = r.get("group") or d
            tree.setdefault(d, {}).setdefault(g, []).append(r)

        final = {
            "scraped_at": datetime.utcnow().isoformat() + "Z",
            "url": URL,
            "total_sub_items": len(all_records),
            "dimensions": [
                {
                    "name": dim,
                    "groups": [
                        {
                            "name": g,
                            "sub_items": [
                                {
                                    "name": r["name"],
                                    "type": r.get("type", "unknown"),
                                    "radios": r.get("radios", []),
                                    "options_flat": r.get("options_flat", []),
                                    "options_by_mode": r.get("options_by_mode", {}),
                                    "modal_text": r.get("modal_text", ""),
                                    "ok": r.get("ok", False),
                                    "error": r.get("error"),
                                }
                                for r in items
                            ],
                        }
                        for g, items in groups.items()
                    ],
                }
                for dim, groups in tree.items() if groups
            ],
        }
        final_json.write_text(
            json.dumps(final, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print()
        print("=" * 70)
        print(f" 完成！总共 {len(all_records)} 行 progress")
        ok_count = sum(1 for r in all_records if r.get("ok"))
        print(f" 成功 {ok_count} / 失败 {len(all_records) - ok_count}")
        print(f" 进度文件: {progress_file}")
        print(f" 完整 JSON: {final_json}")
        print(f" 弹窗截图: {snap_dir}")
        print("=" * 70)

        await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
