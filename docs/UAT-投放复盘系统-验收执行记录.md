# 投放复盘系统 — UAT 验收执行记录

> 依据：`docs/UAT-投放复盘系统.md`  
> 执行方式：代码与接口对照 + 离线脚本（CSV 解析）+ 需在完整 Docker 环境人工点验的项单独标注  
> 日期：2026-04-08

---

## 1. 验收前置（§1.3）

| 检查项 | 结论 | 说明 |
|--------|------|------|
| 全量容器 healthy | **需现场** | 执行 `docker compose ps`，依赖本机编排 |
| AI Hub 已配置 Key | **需现场** | 影响 TC-7.x、端到端步骤 8/12 |
| 知识引擎可建库 | **需现场** | 影响 TC-9.x、RAG |
| SP6 ≥2 条已完成视频 | **需现场** | 影响 TC-5.x、步骤 6 |
| 千川样例 CSV（≥3 行） | **需现场** | 影响 TC-4.x、步骤 5 |

---

## 2. 功能用例结论汇总

**图例**：✅ 实现与文档一致 / ⚠️ 部分满足或依赖人工确认 / ❌ 未实现 / 🔧 需联机验证

### 2.1 产品管理

| 编号 | 结论 | 证据摘要 |
|------|------|----------|
| TC-1.1 | ✅ | `campaigns` 创建时 `_resolve_product_id`：无则 `INSERT products` |
| TC-1.2 | ✅ | 同文件 `LOWER(TRIM(name))` 匹配已有产品，不重复插入 |

### 2.2 投放批次

| 编号 | 结论 | 证据摘要 |
|------|------|----------|
| TC-2.1 | ✅ | 创建默认 `status=draft`；前端跳转 `/ad-review/[id]` |
| TC-2.2 | ✅ | 列表 `ORDER BY start_date DESC`，卡片含产品名、周期、消耗、状态 |
| TC-2.3 | ✅ | `GET /campaigns?product_id=` 与首页筛选 |
| TC-2.4 | ✅ | `confirm` + `DELETE`；DB `ON DELETE CASCADE` 人群包/素材/日志 |

### 2.3 人群包

| 编号 | 结论 | 证据摘要 |
|------|------|----------|
| TC-3.1 | ✅ | Tab 内创建 + 标签拆分 |
| TC-3.2 | ✅ | 每人群包「圈包手法」文本区 +「保存文本」→ `PUT /audiences/{id}` |
| TC-3.3 | ⚠️ | 支持上传 `.xlsx/.xls` 并落盘、界面展示**已存附件路径**；**无独立下载链接**（需后续加静态下载 API） |
| TC-3.4 | ✅ | 同批次多人人群包；CSV 按 `audience_pack_id` 隔离 |

### 2.4 CSV 导入

| 编号 | 结论 | 证据摘要 |
|------|------|----------|
| TC-4.1 | ✅ | UTF-8 / `utf-8-sig`；预览 `preview=true` 返回映射 + 前 3 行 |
| TC-4.2 | ✅ | `chardet` → `gbk` 分支；离线脚本 `scripts/verify_csv_parser.py` 已覆盖 |
| TC-4.3 | ✅ | `花费`→`cost` 在 `COLUMN_MAPPING` |
| TC-4.4 | ✅ | 导入写库 + `enrich_material_metrics`（`play_3s_rate` 等） |
| TC-4.5 | ✅ | `--`/空 → `None`；表格 `null` 显示 `-` |
| TC-4.6 | ✅ | `_refresh_campaign_total_cost` 汇总 `SUM(cost)` |

**脚本**：`services/ad-review-service/scripts/verify_csv_parser.py`（UTF-8 BOM、GBK、`花费`、空值）

### 2.5 视频关联

| 编号 | 结论 | 证据摘要 |
|------|------|----------|
| TC-5.1 | ✅ | 弹窗列表；`status=done` 时并行拉取详情展示 **综合评分/10** 与更新时间 |
| TC-5.2 | ✅ | 关联后 `video_analysis_scores` 缓存；列表行展示「视频综合分」 |
| TC-5.3 | ✅ | `PUT link-video` + `{"video_analysis_id":null}` |

### 2.6 迭代追踪

| 编号 | 结论 | 证据摘要 |
|------|------|----------|
| TC-6.1 | ✅ | `link-parent`；文案「迭代自『父素材名』」+ `version` |
| TC-6.2 | ✅ | 「迭代历史」→ `GET .../iteration-chain` 弹窗表格 |
| TC-6.3 | ✅ | 表中「较上一版 CTR」涨跌幅百分比 |

### 2.7 智能复盘

| 编号 | 结论 | 证据摘要 |
|------|------|----------|
| TC-7.1 | 🔧 | SSE + Prompt 结构含亮点/建议/标签；需联机看 LLM 输出 |
| TC-7.2 | 🔧 | `review_engine` 拉取 `report` 写入 prompt；需联机 |
| TC-7.3 | 🔧 | `_build_iteration_diffs` 注入 prompt；需联机 |
| TC-7.4 | 🔧 | RAG 调 SP4 `/knowledge/rag`；依赖经验库有数据；需联机 |
| TC-7.5 | ✅ | 流式 append + 按钮文案「流式输出」；无单独进度条（仅 loading 态） |
| TC-7.6 | ✅ | `httpx` 120s 超时 + 追加提示文案，已生成内容保留在页面 state |

### 2.8 复盘编辑与保存

| 编号 | 结论 | 证据摘要 |
|------|------|----------|
| TC-8.1 | ✅ | 编辑模式：左 Markdown 右 **实时预览**（`react-markdown`） |
| TC-8.2 | ✅ | `PUT /review` 设 `is_edited`；`campaigns.status=reviewed` |
| TC-8.3 | ✅ | 标签文本区随 `saveReview` 提交 |
| TC-8.4 | ✅ | 「重新生成」+ `confirm` + `replace=1` |

### 2.9 知识库沉淀

| 编号 | 结论 | 证据摘要 |
|------|------|----------|
| TC-9.1 | 🔧 | `sync_review_to_kb` + 前端 `alert`；需 SP4 正常 |
| TC-9.2 | ✅ | `ensure_review_kb` 按名称创建「投放复盘经验库」 |
| TC-9.3 | 🔧 | 依赖知识库问答页选 KB 与 RAG；**需人工在 /knowledge 或问答 UI 验证** |
| TC-9.4 | ✅ | 同步前 `DELETE` 旧 `kb_document_id`（若存在） |

### 2.10 趋势分析（P2）

| 编号 | 结论 | 证据摘要 |
|------|------|----------|
| TC-10.1 | ⚠️ | 有折线图（平均 CTR%、总消耗）；**无 CVR**（库中无统一转化字段） |
| TC-10.2 | ✅ | `audience-compare` 表格 |

---

## 3. 端到端流程（§3.1）

| 步骤 | 结论 | 说明 |
|------|------|------|
| 1–7 | ✅/🔧 | 功能路径已具备；6–7 依赖 SP6 与数据 |
| 8 | 🔧 | 依赖 LLM |
| 9–10 | ✅ | 编辑、同步逻辑具备 |
| 11–12 | 🔧 | 依赖知识库问答 UI 与二次批次实测 |

---

## 4. 非功能（§4）

### 4.1 性能

| 项 | 结论 |
|----|------|
| 各项阈值 | **需现场计时**（UAT 已给方法） |

### 4.2 编码兼容

| 项 | 结论 |
|----|------|
| UTF-8 / BOM / GBK / 混合列名 | ✅ 代码路径 + 离线脚本覆盖 |

### 4.3 异常处理

| 项 | 结论 |
|----|------|
| 空 CSV | ✅ `文件为空` |
| 非 CSV 扩展 | ✅ `请上传 CSV 文件` |
| 列名不匹配 | ❌ **无手动列映射 UI**（IMPL 已知缺口） |
| LLM 不可用 | ⚠️ **401/403** 提示「请先配置 AI…」；其它 4xx 为泛化文案 |
| 知识库不可用 | ✅ 502 文案「知识库服务不可用，请稍后重试。」 |
| 超时 | ✅ 见 TC-7.6 |

### 4.4 数据完整性

| 项 | 结论 |
|----|------|
| 删批次级联 | ✅ Schema CASCADE |
| 删人群包级联 | ✅ 素材挂 `audience_pack_id` CASCADE |
| 删父素材 | ✅ `parent_material_id ON DELETE SET NULL` |
| 知识库单文档 | ✅ 同步前删旧文档 |

---

## 5. 签字区（现场补全）

| 角色 | 姓名 | 日期 | 签字 |
|------|------|------|------|
| 产品确认 | | | |
| 开发确认 | | | |
| 测试确认 | | | |

---

## 6. 建议的联机复测命令（可选）

```bash
# CSV 解析离线自测
cd services/ad-review-service && set PYTHONPATH=. && python scripts/verify_csv_parser.py

# 健康检查（服务已启动且映射 8008）
curl -s http://localhost:8008/health
```

完整 UAT 仍需：**Docker 全栈 + 真实 CSV + SP6 视频 + 已配置 LLM** 下按 `docs/UAT-投放复盘系统.md` 勾选原始用例表。
