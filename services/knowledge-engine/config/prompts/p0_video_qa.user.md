冻结真相快照：
{truth_snapshot_json}

ContentSpec：
{content_spec_json}

冻结的最终提示词：
{final_prompt}

只输出一个完整 JSON 对象，不要 Markdown。`evidence` 最多 6 条，每条不超过 60 个汉字；宁可简短，不要在数组或字符串中途截断。

格式：
{{"decision":"passed","reason_codes":[],"evidence":[""]}}
