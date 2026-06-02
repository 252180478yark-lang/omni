## 反推任务

请反推附件视频（已通过 Gemini Files API 上传给你）。

---

## 老板临时方向

{extra_context_block}

---

## 占位符期望数

| 维度 | 期望数 |
|---|---|
| 产品占位符（`{{product_ref_N}}`） | {product_ref_count} |
| 人脸占位符（`{{face_ref_N}}`） | {face_ref_count} |

**注意**：这是**期望数**，不强制。视频里实际有几个不同的产品/人脸由你判断；
跟期望数不一致时，在 `meta.warnings` 里说明（不报错）。

---

## 方法论偏向（可选）

{target_kind_block}

---

## 输出要求

1. **严格 JSON 输出**（response_mime_type 已设为 application/json）
2. 不要 markdown 围栏，不要说话内容（"好的我来反推"这类）
3. 字段完整性：所有 scene 必须包含 19 个字段（16 结构化 + 3 prompt 包），不允许漏字段
4. 占位符语法：`{{product_ref_1}}` / `{{face_ref_1}}` 等（双花括号在这个用户消息里是转义，实际输出用单花括号）
5. 时间精度：`time_range` 精确到 0.1s，scene 不重叠，总 duration 跟视频时长差 ≤ 0.5s
6. 方法论：必从 8 个白名单选 primary
7. 完播率：必从 `<5%` / `5-15%` / `>15%` 三选一
8. 禁词遵守 §六.6.1 清单
9. 反幻觉：编不出的字段写空字符串/空数组

直接输出 JSON。
