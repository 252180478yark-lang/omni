# omni-vibe Claude Code 指令

> 这文件是给 Claude Code（agent 主大脑）看的，不是产品文档。

## omni MCP server

omni 暴露 10 个 tool（W1 5 个 + W2 5 个）：
- 查询：`list_skus`, `get_sku`, `list_kbs`, `search_kb`, `list_briefs`, `query_costs`
- 算账：`compute_margin`
- 生成：`generate_brief`, `generate_image`, `generate_video`

调用见 `services/knowledge-engine/app/mcp/tools/`。

## sku 出片标准链路（老板说"sku-X 全链路"时按此走）

1. 调 `query_costs(sku_id)` 拿成本
2. 调 `compute_margin(sku_id, channel)` 算利润，给老板审；老板满意进 3
3. 调 `generate_brief(sku_id, channel)` 出 brief，给老板审；老板满意进 4
4. 调 `generate_image(prompts=[3 个分镜 prompt], face_refs/product_refs)` 出 3 张分镜图，给老板审；老板满意进 5
5. 调 `generate_video(segments=[3 段 prompt + 首尾帧链], face_refs, product_refs)` 出 3 段视频，给老板下载

每步跑完把 result + trace + next_step_hint 都给老板看。**不要一气呵成跑完整套**——每步停下来等老板反馈。

## 老板响应词约定

| 老板说 | 含义 | Claude 应做 |
|---|---|---|
| OK / 继续 / 赞 / 通过 / 进下一步 | 当前 step 满意，进下一步 | 按 next_step_hint.suggested_tool + suggested_args 调下一个 tool |
| 重来 / 改 / 不行 / 重跑 | 当前 step 不满意 | 用同 tool 重调，参数照老板新说法改（如老板说"prompt 加 X"，把 X 加进 prompt） |
| 第 N 张重来 / 第 N 段重做 | 局部重跑 | 只重调那一段（generate_image 单独一个 prompt；generate_video 单独一个 segment） |
| 跳过 X / 不要这步 | 跳一步 | 不调 X，按链路下一步走 |
| 全链路 / 跑通 | 触发标准链路 | 从 step 1 query_costs 起按上面 5 步走，每步停下等老板反馈 |

## 已知约束

- 不调 `run_sku_orch` —— W2 没这个 tool，编排靠对话
- LLM tool 必返 `trace` 字段，老板要看 final_prompt 才能调 prompt 重跑
- video 多段并发跑（asyncio.gather），typically 30-60s 每段；并发后总时间 ≈ 单段
- 所有 W2 tool 都不走 Human Gate（W1 stub 保留给 W3）

## 调试

- 容器内自检：`docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -m app.mcp.doctor"`
- 审计表：`docker exec omni-postgres psql -U omni_user -d omni_vibe_db -c "SELECT tool_name, status, duration_ms FROM mcp.tool_calls ORDER BY created_at DESC LIMIT 20"`
- ai-provider-hub 状态：`curl http://localhost:8001/api/v1/ai/providers`
