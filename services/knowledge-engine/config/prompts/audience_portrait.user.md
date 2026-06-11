## ① 产品基本信息

{sku_md}

## ② 卖点矩阵（step 2 输出，第 2 部分卖点重构从这里挑）

{matrix_md}

## ③ 老板选中的人群（step 3 输出，本次唯一深挖对象）

- 人群名：{audience_name}
- KB 来源：{audience_kb_doc}
- 圈层标签：{audience_layer_tags}
- step 3 匹配理由：
{audience_match_reasons_md}
- step 3 的 KB 原文段：
> {audience_kb_chunk}

## ④ 四路定向 KB 召回（本圈层深挖 / 生活维度扫描 / 八大情绪交叉 / 卖点反打）

> 这是 tool 内部对**这一个人群**做的定向二次召回（跟 step 3 的广撒网相反，这轮是深挖）。
> 写画像时**只能用这里 + ③ 的 KB 原文当 [KB:] 锚点**；这里没有的，要么 🧠推演（写明锚点）要么 ⚠️推测（≤5 处）要么进第 4 部分缺口。

{kb_recall}

## ⑤ 额外要求

{extra_context}

---

请按 system prompt「输出结构」严格输出 5 部分（第 0 速写 / 第 1 生活状态画像 5 小节 / 第 2 卖点重构 3-5 条 / 第 3 情绪触点矩阵 / 第 4 信息缺口）。

输出前按「输出前强制自检」逐条核对，不达标必须重写。
