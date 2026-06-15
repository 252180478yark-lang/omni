【被评工具】{tool}

【评分维度卡 rubric】
{rubric}

【生成时输入摘要（冻结输入）】
{input_summary}

【黄金样本（老板采纳/好评过的产物，质量基准）】
<golden>
{golden}
</golden>

【本次新产物（待评）】
<candidate>
{candidate}
</candidate>

【确定性层已发现的问题（参考，勿重复机械检查）】
{det_warnings}

按 system 要求输出严格 JSON（只一个 JSON 对象，无围栏无解释）。
