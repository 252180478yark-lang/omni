冻结真相快照：
{truth_snapshot_json}

ContentSpec：
{content_spec_json}

ContentSpec 哈希：{content_spec_hash}
真相快照哈希：{truth_snapshot_hash}
本次附加要求：{extra_context}

先把 ContentSpec 内 `pain_solution_bridge` 的六段因果逐项映射到候选：触发场景和痛点在前 3 秒出现；产品动作在中段真实发生；可见结果和认知变化在结尾出现。两个候选只能改变 `opening_hook_3s` 的表达，不能改变任何桥字段、证据、节拍因果或结果。

只输出以下 JSON 结构。`candidates` 必须恰好两项，且每项都有全部字段；`factual_claims` 只能从 ContentSpec 与冻结真相共有的白名单逐字选取。

{{"candidates":[{{"opening_hook_3s":"","body":"","spoken_copy":"","beat_plan":[{{"start_seconds":0,"end_seconds":3,"visual":"","action":"","spoken_copy":"","sound":""}},{{"start_seconds":3,"end_seconds":6,"visual":"","action":"","spoken_copy":"","sound":""}},{{"start_seconds":6,"end_seconds":9,"visual":"","action":"","spoken_copy":"","sound":""}},{{"start_seconds":9,"end_seconds":12,"visual":"","action":"","spoken_copy":"","sound":""}}],"product_action":"","duration_seconds":12,"factual_claims":[""],"content_spec_hash":"{content_spec_hash}","truth_snapshot_hash":"{truth_snapshot_hash}"}},{{"opening_hook_3s":"","body":"","spoken_copy":"","beat_plan":[{{"start_seconds":0,"end_seconds":3,"visual":"","action":"","spoken_copy":"","sound":""}},{{"start_seconds":3,"end_seconds":6,"visual":"","action":"","spoken_copy":"","sound":""}},{{"start_seconds":6,"end_seconds":9,"visual":"","action":"","spoken_copy":"","sound":""}},{{"start_seconds":9,"end_seconds":12,"visual":"","action":"","spoken_copy":"","sound":""}}],"product_action":"","duration_seconds":12,"factual_claims":[""],"content_spec_hash":"{content_spec_hash}","truth_snapshot_hash":"{truth_snapshot_hash}"}}]}}
