# 三平台取数底座 — 实时重验报告（2026-06-01）

> 登录态实测 491 端点；verified = 今天真能取到数据（PASS/PASS_NODATA）。


**合计：180/491 = 36% 可用**；testcase 可靠层 138/192 = 71%


## yuntu：94/202 可用（testcase 层 68/93 = 73%）

**可用端点（按域族）：**

- `其它`：68 个
- `search_node/api/search`：12 个
- `yuntu_ng/api/v1`：5 个
- `yuntu_ai_marketer/api/v1`：3 个
- `ai_marketer_api`：3 个
- `measurement/api/eva`：3 个

**待修 backlog**：{'FAIL_OTHER': 15, 'FAIL_404': 75, 'FAIL_AUTH': 9, 'FAIL_DRIFT': 9}

## compass：43/192 可用（testcase 层 42/61 = 68%）

**可用端点（按域族）：**

- `其它`：43 个

**待修 backlog**：{'FAIL_OTHER': 16, 'FAIL_404': 8, 'FAIL_AUTH': 2, 'FAIL_DRIFT': 123}

## doudian：43/97 可用（testcase 层 28/38 = 73%）

**可用端点（按域族）：**

- `其它`：43 个

**待修 backlog**：{'FAIL_OTHER': 17, 'FAIL_404': 22, 'FAIL_AUTH': 1, 'FAIL_DRIFT': 14}