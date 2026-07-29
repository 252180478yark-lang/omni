---
name: yuntu-audience-automation
description: Use when a generated Yuntu audience pack should be applied, dry-run, checked, or pushed in 巨量云图 after the user adopts or approves the pack. Use a logged-in Chrome controller or Computer Use to carry out the approved UI steps; do not stop at a CDP-only check.
---

# yuntu-audience-automation

## Scope

This skill owns the transition from an adopted SOP to the actual Yuntu web UI. A successful Chrome CDP probe is evidence that a session exists; it is not the UI actuator. When a supported controller is available, do not stop with “cannot control the computer” after preflight.

## Principle

Automate only after approval. A generated pack may describe the right audience, but browser execution can dirty the live Yuntu account. The execution gate is:

```text
pack_status=adopted + explicit approval + dry-run clean
```

Final save/push additionally requires `--allow-final-submit`.

## Default Flow

1. Read the adopted audience pack SOP, keyword pack, and Yuntu source graph.
2. Run `scripts/yuntu_audience_automation.py` in dry-run first.
3. Confirm the SOP contains backend executable checks and `关键词池 0/500`.
4. Confirm the user has explicitly asked to execute the adopted pack. If the user has only adopted it without asking to apply it, stop before the first browser write and ask.
5. Open the logged-in Chrome/Yuntu session with a supported controller.
6. Create keyword package and data-factory tags.
7. Create custom audience units.
8. Combine units and read/screenshot the `预估人数`.
9. Export the final audience profile / 导出画像, then run 圈包准度验收 before declaring success.
10. If the base is too large, too small, or volume is acceptable but precision is weak, hand off to `audience-pack-sizing`.
11. Only after an immediate final confirmation, save/push with `--allow-final-submit`.

## Desktop Execution

Use a controller attached to the user's already logged-in Yuntu session:

1. Prefer a browser-native Chrome controller when it can target that exact logged-in page. Otherwise invoke `computer-use:computer-use` to control the Windows Chrome window.
2. Before Computer Use acts, follow its SKILL.md setup and confirmation rules. Select exactly one Chrome window returned by the controller whose URL/title identifies `yuntu.oceanengine.com`; never guess a window handle or click a similarly named window.
3. Work in a strict observation loop: inspect the current page, take one click/type/scroll action, refresh the page state, and verify the expected Yuntu result before the next action. Re-observe after navigation, modal changes, errors, or a failed input; do not reuse old coordinates, screenshot IDs, or accessibility indexes.
4. Follow the adopted SOP exactly when creating keyword packs, tag-factory tags, custom audience units, and combination formulas. Capture evidence after each completed stage, especially the `预估人数` preview and exported profile.
5. CDP remains useful for read-only session discovery and preflight. A missing CDP endpoint is not by itself a reason to abandon execution when the logged-in Chrome window is targetable through Computer Use.

Do not automate login, passwords, OTPs, CAPTCHA challenges, browser security interstitials, or permission dialogs. Ask the user to take over for those steps, then resume from a fresh observation.

## Safety Gates

- Never execute live writes for draft packs. Require `pack_status=adopted`.
- Never click final save or push without `--allow-final-submit`.
- Treat creation of keyword packs, tags, audience units, and combinations as browser writes: begin them only after pack adoption, a clean dry-run, and the user's explicit request to execute.
- Ask for confirmation immediately before the final Save/Push click, even when the user previously approved the execution run.
- Always run dry-run and save a JSON plan before browser writes.
- Always capture a screenshot / 截图 around `预估人数` before deciding success.
- 人数合适不能直接宣告完成. Always export the audience profile and run 圈包准度验收 first.
- Keywords go to 云图数据工厂, not 千川关键词定向.
- Do not convert a non-commerce pack into 商品人群标签 or 电商成交标签 to fix volume.

## Runner

Use:

```powershell
python scripts/yuntu_audience_automation.py `
  --pack-id <audience_pack_id> `
  --pack-status adopted `
  --sop <pack.md> `
  --keywords <keywords.txt> `
  --output <preflight.json>
```

The script reports:

- whether dry-run is clean
- whether final submit is enabled
- keyword count
- backend executable check count
- detected formula such as `A ∩ (B ∪ C)`
- whether a Yuntu page is attached through Chrome CDP

## Sizing Handoff

After a Yuntu preview shows the audience base:

- Too small: call `audience-pack-sizing` to loosen time window, frequency, content items, age, geography, or union formula. 不要一开始就 lookalike.
- Too large: call `audience-pack-sizing` to add intent, intersection, frequency, recency, or exclusions while preserving scene-chain logic.
- Acceptable size but weak exported profile: call `audience-pack-sizing` with the 量级满意但准度不足 branch. Keep it as reach_master / 内容探索包 if appropriate, and create a separate precision_core pack for harvesting.
- The sizing agent must use real Yuntu `预估人数`, screenshot, or exported result, not guesses.

## Stop Conditions

Stop and ask before saving when:

- login/session is missing
- SOP has missing backend executable checks
- keyword count is below 500 for a reach pack
- Yuntu options differ from the source graph
- user has not adopted the pack
- user has not explicitly asked to execute the adopted pack
- no supported controller can reach the logged-in Yuntu window, or more than one candidate window matches
- login, OTP, CAPTCHA, browser-security, or permission UI requires user take-over
- the observed Yuntu control or result does not match the adopted SOP, or the outcome of an input action is unknown
- the preview size misses the target range
- 导出画像 is unavailable after execution
- 圈包准度验收 has not labeled pack type, bottom/base contribution, intent-layer contribution, 泛兴趣污染, and content inheritance direction
