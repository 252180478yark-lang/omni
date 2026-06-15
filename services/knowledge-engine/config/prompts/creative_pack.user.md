{experiment_constraint}

## ① 当前任务

**素材类型**：{kind_label}（kind = `{kind}`）

按 system 里的固定输出结构，给下面的 SKU + 人群 + 卖点矩阵写一份 {kind_label} 创意稿。

---

## ② SKU 信息

{sku_md}

---

## ③ 卖点矩阵（来自 step 2，节号沿用；卖点引用必须用这个节号系统）

{matrix_md}

---

## ④ 目标人群（来自 step 3，可能为空 — 单 SKU 模式时直接出"通用画像"）

{audience_md}

---

## ⑤ 圈包参考（来自 step 4，可能为空 — 没跑 step 4 时绕过）

{audience_pack_summary}

---

## ⑥ 老板临时要求（extra_context）

{extra_context}

---

## ⑦ 目标出片模型写法档案（video_* kind 的「AI 出片提示词」部分必须按此档案的语言/真人感锚/负向词写；分块规则以 system prompt 的拆块铁律为准）

{target_model_profile}

---

## ⑧ 输出

按 system 里的固定 markdown 结构输出。**只输出 markdown 内容**，不要包裹代码块，不要写"好的我来"等说话。
