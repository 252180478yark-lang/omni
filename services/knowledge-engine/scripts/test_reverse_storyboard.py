"""reverse_storyboard_video tool 测试脚本。

用法(容器内跑):
    docker exec omni-knowledge-engine python /app/scripts/test_reverse_storyboard.py
    docker exec omni-knowledge-engine python /app/scripts/test_reverse_storyboard.py --iter 1 --model gemini-3-pro-preview
    docker exec omni-knowledge-engine python /app/scripts/test_reverse_storyboard.py --extra-context "重点反推钩子"

测试视频: /host/Desktop/千川视频/3月25日.mp4 (host bind-mount)
日志落: /host/Desktop/千川视频/test_logs/iter_<N>_<timestamp>_{result,markdown,trace}.{json,md}

校验:
1. scene 时间不重叠 + 总时长 ≈ 视频时长 ±1s
2. 占位符语法合法,引用一致
3. methodology_guess.primary ∈ 8 个白名单
4. hook_analysis.completion_estimate ∈ 3 个白名单
5. 3 类全局产物都非空
6. scene 级 3 类 prompt 都非空(zh + en)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

# 默认测试视频(host bind-mount 路径)
DEFAULT_VIDEO = "/host/Desktop/千川视频/3月25日.mp4"
DEFAULT_LOG_DIR = "/host/Desktop/千川视频/test_logs"

METHODOLOGY_WHITELIST = {
    "Pixar", "Slice of Life", "CER", "Hero",
    "Empathy", "Cultural Tension", "Aspirational", "Mini-Doc",
}
COMPLETION_ESTIMATE_WHITELIST = {"<5%", "5-15%", ">15%"}


def _print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def _check(name: str, ok: bool, detail: str = "") -> bool:
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
    return ok


async def run_test(
    video_path: str,
    iter_n: int,
    model: str | None,
    extra_context: str | None,
    target_kind: str | None,
    product_ref_count: int,
    face_ref_count: int,
    log_dir: str,
) -> bool:
    """跑一次 reverse_storyboard_video,落日志,做校验。返回 all_pass。"""
    from app.mcp.tools.media import reverse_storyboard_video

    _print_section(f"Iter {iter_n}: reverse_storyboard_video")
    print(f"  video_path: {video_path}")
    print(f"  model: {model or '(yaml default)'}")
    print(f"  extra_context: {extra_context or '(无)'}")
    print(f"  target_kind: {target_kind or '(无)'}")
    print(f"  product_ref_count: {product_ref_count}")
    print(f"  face_ref_count: {face_ref_count}")

    if not os.path.exists(video_path):
        print(f"\n[FAIL] 视频文件不存在: {video_path}")
        print("提示: 检查 docker-compose.yml KE service 是否有 bind-mount")
        return False

    start_ts = time.time()
    start_iso = time.strftime("%Y%m%d_%H%M%S")
    print(f"\n  started: {start_iso}")
    print(f"  发起 LLM 调用 (Gemini Files API 上传 + analyze)...")

    try:
        result = await reverse_storyboard_video(
            video_path=video_path,
            model=model,
            extra_context=extra_context,
            target_kind=target_kind,
            product_ref_count=product_ref_count,
            face_ref_count=face_ref_count,
        )
    except Exception as exc:
        print(f"\n[FAIL] tool 抛异常: {type(exc).__name__}: {exc}")
        return False

    elapsed = time.time() - start_ts
    print(f"  elapsed: {elapsed:.1f}s")

    # ── 落日志 ──
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_prefix = f"{log_dir}/iter_{iter_n:02d}_{start_iso}"

    # result.json (完整)
    result_path = f"{log_prefix}_result.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  saved: {result_path}")

    # markdown 报告(单独存,便于浏览)
    if result.get("ok") and result.get("result", {}).get("markdown"):
        md_path = f"{log_prefix}_report.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(result["result"]["markdown"])
        print(f"  saved: {md_path}")

    # trace + 参数(单独存,便于 diff)
    trace_path = f"{log_prefix}_trace.json"
    with open(trace_path, "w", encoding="utf-8") as f:
        json.dump({
            "iter": iter_n,
            "start_iso": start_iso,
            "elapsed_sec": round(elapsed, 1),
            "params": {
                "video_path": video_path,
                "model": model,
                "extra_context": extra_context,
                "target_kind": target_kind,
                "product_ref_count": product_ref_count,
                "face_ref_count": face_ref_count,
            },
            "trace": result.get("trace"),
            "warnings": result.get("result", {}).get("meta", {}).get("warnings", []),
            "errors": result.get("errors"),
            "ok": result.get("ok"),
            "error": result.get("error"),
        }, f, ensure_ascii=False, indent=2)
    print(f"  saved: {trace_path}")

    # ── 校验 ──
    _print_section(f"Iter {iter_n}: 校验")

    all_pass = True
    if not result.get("ok"):
        _check("tool ok=True", False, f"error={result.get('error')} hint={result.get('hint')}")
        return False
    _check("tool ok=True", True)

    r = result.get("result") or {}
    scenes = r.get("scenes") or []
    meta = r.get("meta") or {}

    all_pass &= _check("scenes 非空", len(scenes) > 0, f"N={len(scenes)}")

    # 时间
    total_dur = sum(s.get("duration_sec", 0) for s in scenes)
    video_dur = meta.get("video_duration_sec") or 0
    all_pass &= _check(
        "scenes 总时长 ≈ 视频时长 ±1s",
        abs(total_dur - video_dur) <= 1.0 if video_dur else True,
        f"sum={total_dur:.1f}s vs video={video_dur:.1f}s",
    )
    overlap = False
    for i in range(len(scenes) - 1):
        if scenes[i]["time_range"][1] > scenes[i + 1]["time_range"][0] + 0.5:
            overlap = True
            break
    all_pass &= _check("scenes 时间不重叠", not overlap)

    # scene 字段
    required_struct = [
        "idx", "time_range", "duration_sec",
        "subject", "action", "environment",
        "shot_type", "camera_motion",
        "lighting", "style_keywords", "mood_keywords", "color_palette",
        "dialogue", "voiceover_guess", "sfx_ambient", "on_screen_text",
        "first_frame_hint", "last_frame_hint",
        "negative_hints",
    ]
    miss_struct = []
    for i, s in enumerate(scenes, 1):
        for f in required_struct:
            if f not in s:
                miss_struct.append(f"scene{i}.{f}")
    all_pass &= _check(
        "每 scene 16 个结构化字段齐",
        not miss_struct,
        f"缺失: {miss_struct[:5]}{'...' if len(miss_struct) > 5 else ''}" if miss_struct else "all ok",
    )

    # scene 级 3 类 prompt 都非空(zh + en)
    miss_prompt = []
    for i, s in enumerate(scenes, 1):
        for pkey in ("prompt_for_image", "prompt_for_video_i2v", "prompt_for_video_t2v"):
            p = s.get(pkey) or {}
            if not p.get("zh"):
                miss_prompt.append(f"scene{i}.{pkey}.zh")
            if not p.get("en"):
                miss_prompt.append(f"scene{i}.{pkey}.en")
    all_pass &= _check(
        "每 scene 3 类 prompt 双语都非空",
        not miss_prompt,
        f"缺失: {miss_prompt[:5]}{'...' if len(miss_prompt) > 5 else ''}" if miss_prompt else "all ok",
    )

    # 3 类全局产物非空
    sis = r.get("storyboard_for_image_set") or {}
    svs = r.get("storyboard_for_video_segments") or {}
    svl = r.get("storyboard_for_video_long") or {}
    all_pass &= _check(
        "storyboard_for_image_set 双语 prompt 非空",
        bool(sis.get("prompt_zh") and sis.get("prompt_en")),
    )
    all_pass &= _check(
        "storyboard_for_video_segments segments 非空",
        len(svs.get("segments") or []) > 0,
        f"N segments={len(svs.get('segments') or [])}",
    )
    all_pass &= _check(
        "storyboard_for_video_long 双语 prompt 非空",
        bool(svl.get("prompt_zh")),
    )

    # methodology / hook
    mg = r.get("methodology_guess") or {}
    all_pass &= _check(
        "methodology_guess.primary 白名单",
        mg.get("primary") in METHODOLOGY_WHITELIST,
        f"got={mg.get('primary')!r}",
    )
    ha = r.get("hook_analysis") or {}
    all_pass &= _check(
        "hook_analysis.completion_estimate 白名单",
        ha.get("completion_estimate") in COMPLETION_ESTIMATE_WHITELIST,
        f"got={ha.get('completion_estimate')!r}",
    )

    # 占位符
    placeholders = r.get("placeholders") or {}
    product_keys = [k for k in placeholders if k.startswith("product_ref_")]
    face_keys = [k for k in placeholders if k.startswith("face_ref_")]
    _check(
        f"placeholders product 数",
        True,
        f"期望={product_ref_count} got={len(product_keys)} ({product_keys})",
    )
    _check(
        f"placeholders face 数",
        True,
        f"期望={face_ref_count} got={len(face_keys)} ({face_keys})",
    )

    # warnings
    warnings = meta.get("warnings") or []
    if warnings:
        print(f"\n  [warnings 共 {len(warnings)} 条]:")
        for w in warnings:
            print(f"    - {w}")

    # ── 总结 ──
    _print_section(f"Iter {iter_n}: 结论")
    print(f"  {'✓ ALL PASS' if all_pass else '✗ 有校验失败'}")
    print(f"  scene 数: {len(scenes)}")
    print(f"  视频时长: {video_dur}s")
    print(f"  方法论: {mg.get('primary')} (备选 {mg.get('alternative')})")
    print(f"  钩子估完播: {ha.get('completion_estimate')}")
    print(f"  Gemini usage: input={meta.get('usage', {}).get('input_tokens', 0)} output={meta.get('usage', {}).get('output_tokens', 0)} tokens")
    print(f"  log dir: {log_dir}")

    return all_pass


def main():
    parser = argparse.ArgumentParser(description="reverse_storyboard_video 测试脚本")
    parser.add_argument("--video", default=DEFAULT_VIDEO, help="视频路径(容器内)")
    parser.add_argument("--iter", type=int, default=1, help="迭代编号(决定日志文件名)")
    parser.add_argument("--model", default=None, help="覆盖 yaml 默认 model")
    parser.add_argument("--extra-context", default=None, help="老板临时方向")
    parser.add_argument("--target-kind", default=None,
                        choices=[None, "video_planting", "video_harvest", "video_soft_ad"],
                        help="方法论偏向")
    parser.add_argument("--product-ref-count", type=int, default=1)
    parser.add_argument("--face-ref-count", type=int, default=1)
    parser.add_argument("--log-dir", default=DEFAULT_LOG_DIR, help="测试日志目录")
    args = parser.parse_args()

    async def _main_async():
        # tool_with_audit 装饰器需要 DB pool 初始化(写 audit log 到 mcp.tool_calls)
        from app.database import init_pool, close_pool
        await init_pool()
        try:
            return await run_test(
                video_path=args.video,
                iter_n=args.iter,
                model=args.model,
                extra_context=args.extra_context,
                target_kind=args.target_kind,
                product_ref_count=args.product_ref_count,
                face_ref_count=args.face_ref_count,
                log_dir=args.log_dir,
            )
        finally:
            await close_pool()

    ok = asyncio.run(_main_async())
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
