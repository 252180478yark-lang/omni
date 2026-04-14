# 角色系统与圆桌会议 — UAT 验收执行记录

> 依据：`docs/UAT-角色系统与圆桌会议.md`  
> 执行方式：代码审查 + 接口对照（代码级验证）；需在完整 Docker 环境人工点验的项单独标注  
> 日期：2026-04-08

---

## 1. 验收前置（§1.3）

| 检查项 | 结论 | 说明 |
|--------|------|------|
| 全量容器 healthy | **需现场** | `docker compose ps` |
| AI Hub 已配置 Key | **需现场** | 影响所有问答和圆桌用例 |
| 知识引擎有文档 | **需现场** | 影响 RAG 类用例 |
| 浏览器支持 PDF | ✅ | 使用 `html2pdf.js` 客户端渲染，兼容 Chrome/Edge/Firefox |

---

## 2. 功能用例结论汇总

**图例**：✅ 实现与文档一致 / ⚠️ 部分满足或依赖人工确认 / ❌ 未实现 / 🔧 需联机验证

### 2.1 角色选择器

| 编号 | 结论 | 证据摘要 |
|------|------|----------|
| TC-1.1 | ✅ | `/chat` 页面顶部渲染 `<PersonaSelector />`；默认 `selectedPersonaId=null` 显示"通用助手" |
| TC-1.2 | ✅ | `PRESET_PERSONAS` 定义 9 个角色，顺序=电商运营→组织管理，每个含 icon+name+description |
| TC-1.3 | ✅ | 选中后 `selectPersona(id)` 更新 store；`exampleQueries` 随角色切换更新显示（`chat/page.tsx:731-739`）|
| TC-1.4 | ✅ | 切换角色仅改 `selectedPersonaId`，`useChatStore` messages 不受影响；后续提问使用新角色 systemPrompt |
| TC-1.5 | ✅ | `selectPersona(null)` 恢复通用助手；systemPrompt 回退到 `DEFAULT_CHAT_SYSTEM` |

### 2.2 单人角色问答

| 编号 | 结论 | 证据摘要 |
|------|------|----------|
| TC-2.1 | 🔧 | 角色 systemPrompt 通过 `persona_prompt` 传入 RAG；后端 `rag_chain.py:339-342` 将其注入 LLM 上下文；需联机验证输出质量 |
| TC-2.2 | 🔧 | 无 KB 时走 `streamDirectChat`，systemPrompt 作为 system message 注入（`chat/page.tsx:432-454`）；需联机 |
| TC-2.3 | 🔧 | 代码路径正确——不同 persona 产生不同 system prompt → LLM 输出应有差异；需联机对比 |
| TC-2.4 | 🔧 | "组织管理"角色 systemPrompt 含结构化输出要求（岗位/职责/薪资/考核）；需联机看实际格式 |
| TC-2.5 | 🔧 | 多 KB RAG 请求 `kbIds` 传数组；persona_prompt 同时注入；需联机验证综合效果 |

### 2.3 角色管理

| 编号 | 结论 | 证据摘要 |
|------|------|----------|
| TC-3.1 | ✅ | `PersonaManager` 弹窗：预设区有"编辑 Prompt"+"恢复默认"；自建区有"编辑"+"删除"；底部"创建新角色" |
| TC-3.2 | ✅ | 编辑预设：`openEdit(p)` → `PersonaEditor` → `updatePersona(id, data)` |
| TC-3.3 | ✅ | `resetPresetPrompt(id)` 从 `getDefaultPresetById()` 还原原始 systemPrompt/name/icon/exampleQueries |
| TC-3.4 | ✅ | `PersonaEditor` 含 name/icon/description/systemPrompt/exampleQueries 字段；`createPersona()` 生成 UUID |
| TC-3.5 | 🔧 | 自建角色出现在 `personas` 列表中，选择器可选；需联机验证问答使用自定义 systemPrompt |
| TC-3.6 | ✅ | `updatePersona(id, data)` 可改 name/systemPrompt 等；选择器读 store 实时更新 |
| TC-3.7 | ✅ | `deletePersona(id)` 含 confirm 确认；若 `selectedPersonaId===id` 则自动回 null |
| TC-3.8 | ✅ | 预设角色行只显示"编辑 Prompt"和"恢复默认"按钮，无"删除"；`deletePersona` 内部也检查 `isPreset` |
| TC-3.9 | ✅ | Zustand `persist` middleware key=`'omni-persona-store'`；`partialize` 保存 `personas` 和 `selectedPersonaId`；`mergePersonaLists` 确保新预设不丢 |

### 2.4 圆桌会议配置

| 编号 | 结论 | 证据摘要 |
|------|------|----------|
| TC-4.1 | ✅ | Chat 页面有 "💬 单人问答" / "🪑 圆桌会议" tab 切换；圆桌 tab 渲染 `<RoundtableView />` |
| TC-4.2 | ✅ | 勾选界面显示"已选 X/5"，每个角色 checkbox |
| TC-4.3 | ✅ | `handleStart()` 检查 `participantIds.length < 2` → 提示"至少选择 2 个参会角色" |
| TC-4.4 | ✅ | `toggleParticipant`: `if (prev.length >= 5)` → setErrorTip('最多选择 5 个参会角色') |
| TC-4.5 | ✅ | `<Select>` 含两项："🤖 默认主持人" (value=default) + "👔 老板视角" (value=boss) |
| TC-4.6 | ✅ | `<Select>` 含 3/4/5 轮选项；`totalRounds` 默认 3 |
| TC-4.7 | ✅ | `handleStart()` 第一个检查：`if (!topic.trim())` → "请输入讨论议题" |

### 2.5 圆桌讨论过程

| 编号 | 结论 | 证据摘要 |
|------|------|----------|
| TC-5.1 | 🔧 | `executeRound()` 通过 SSE POST `/api/omni/roundtable`（action=run-round），后端 `roundtable-controller.ts` 并行发起各角色 RAG；需联机 |
| TC-5.2 | 🔧 | Controller 中每个角色 fetch `/api/omni/knowledge/rag` 带 `kbIds` + `persona_prompt`；需联机验证 |
| TC-5.3 | 🔧 | `roundHistory` payload 含上轮所有发言文本，Controller 组装为"其他角色上一轮发言：..."传入 prompt；需联机看效果 |
| TC-5.4 | ✅ | 每轮 `<details>` 可折叠/展开；卡片显示角色 icon+name；流式输出有 `loading` 指示 |
| TC-5.5 | 🔧 | `handleStart()` 循环 `for (let r = 1; r <= totalRounds; r++)` 执行各轮后自动 `executeSummary()`；需联机 |

### 2.6 用户插话

| 编号 | 结论 | 证据摘要 |
|------|------|----------|
| TC-6.1 | ✅ | `showInterventionPanel` 在轮次间显示插话框；含"全员回应"和"发送"按钮 |
| TC-6.2 | ✅ | "全员回应" `handleInterventionAll()` 不设 `targetPersonaId`，下一轮所有角色收到 intervention 内容 |
| TC-6.3 | ✅ | `parseAtMention()` 正则解析 `@角色名`，提取 `targetPersonaId`；Controller 中仅向目标角色注入此追问 |
| TC-6.4 | ✅ | "跳过插话，进入下一轮" 按钮 → `handleContinueNextRound()` |
| TC-6.5 | ✅ | 插话写入 `interventions` 数组，不计入 for 循环轮数；讨论仍完整执行 `totalRounds` 轮 |

### 2.7 主持人总结

| 编号 | 结论 | 证据摘要 |
|------|------|----------|
| TC-7.1 | 🔧 | Controller 定义 `DEFAULT_MODERATOR_PROMPT` 含七段结构（议题概述/核心观点/共识/分歧/风险/建议/行动项），语气"客观中立"；需联机看实际输出 |
| TC-7.2 | 🔧 | `BOSS_MODERATOR_PROMPT` 口吻为"CEO/创始人"，"简洁直接、关注利润和风险"，含"止损线"要求；需联机 |
| TC-7.3 | 🔧 | 总结 prompt 注入完整发言记录（含角色名），LLM 应引用角色名称；需联机看效果 |

### 2.8 PDF 导出

| 编号 | 结论 | 证据摘要 |
|------|------|----------|
| TC-8.1 | ✅ | 总结完成后显示"📄 导出PDF"按钮（`roundtable-view.tsx`） |
| TC-8.2 | ✅ | 文件名 `圆桌会议_{topic前20字}_{日期}.pdf`；自动下载 |
| TC-8.3 | ✅ | PDF HTML 含：标题"圆桌会议报告"、议题、日期、参会角色、轮数、主持人类型、AI模型信息 + 完整总结 |
| TC-8.4 | ✅ | CSS `font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif`；`html2canvas` 渲染 |

### 2.9 圆桌后切回单人

| 编号 | 结论 | 证据摘要 |
|------|------|----------|
| TC-9.1 | ✅ | `RoundtableView` 组件有 `onContinueSolo` prop → `setChatMode('single')` |
| TC-9.2 | ✅ | 切回后 PersonaSelector 可用，可正常选角色+独立新问答 |

### 2.10 Tri-Mind 替代

| 编号 | 结论 | 证据摘要 |
|------|------|----------|
| TC-10.1 | ⚠️ | 主导航 (`page.tsx`) 无 Tri-Mind 入口链接 ✅。但 `/tri-mind` 页面文件仍存在（`frontend/src/app/tri-mind/page.tsx`），可直接输入 URL 访问。建议删除或重定向 |
| TC-10.2 | ✅ | "🪑 圆桌会议" tab 在 Chat 页面完整可用，功能上替代了 Tri-Mind |

---

## 3. 异常场景验收（§3）

### 3.1 网络与服务异常

| 编号 | 结论 | 证据摘要 |
|------|------|----------|
| TC-E1 | 🔧 | 需联机：AI Hub 宕机时前端 fetch 应 catch 错误并显示提示 |
| TC-E2 | 🔧 | 需联机：Knowledge Engine 不可用时 RAG 请求失败路径 |
| TC-E3 | ✅ | `handleStop()` → `abort()` 中止请求 + `setRunning(false)`；已完成发言保留 |
| TC-E4 | 🔧 | Controller 中 try/catch per persona；单角色失败发 `error` 事件，其他继续；需联机模拟 |

### 3.2 边界条件

| 编号 | 结论 | 证据摘要 |
|------|------|----------|
| TC-E5 | 🔧 | RAG 对空 KB 返回空 context；角色 prompt 仍注入；需联机看 AI 是否说明"未找到内容" |
| TC-E6 | ✅ | 议题无长度限制，直接传入 LLM；textarea 无 maxLength 约束 |
| TC-E7 | ✅ | `systemPrompt` 为空时 → `persona?.systemPrompt?.trim()` 为 falsy → 回退 `DEFAULT_CHAT_SYSTEM` |
| TC-E8 | ✅ | `createPersona` 使用 UUID 作为 id，名称不做唯一性校验；两个同名角色各自独立 |

---

## 4. 验收检查清单（§4.1）

### 功能完整性

| 检查项 | 状态 |
|--------|------|
| 9 个预设角色全部可用 | ✅ |
| 角色选择器正常工作 | ✅ |
| 切换角色保留聊天历史 | ✅ |
| 角色 prompt 影响回答风格 | 🔧 |
| 角色 + 知识库联合工作 | 🔧 |
| 纯角色问答（无知识库）正常 | 🔧 |
| 自建角色 CRUD 完整 | ✅ |
| 预设角色可编辑 prompt、可重置 | ✅ |
| 角色数据 localStorage 持久化 | ✅ |
| 圆桌会议配置面板完整 | ✅ |
| 圆桌参会角色 2-5 个限制 | ✅ |
| 圆桌多轮讨论正常 | 🔧 |
| 圆桌每轮 RAG 检索生效 | 🔧 |
| 后续轮次参考上轮发言 | 🔧 |
| 用户插话（全员回应）正常 | ✅ |
| 用户插话（@指定角色）正常 | ✅ |
| 默认主持人总结结构化输出 | 🔧 |
| 老板视角主持人总结风格正确 | 🔧 |
| PDF 导出正常 | ✅ |
| 圆桌后切回单人深聊 | ✅ |
| Tri-Mind 入口已移除 | ⚠️ |

### 非功能性

| 检查项 | 状态 |
|--------|------|
| 单人角色问答响应速度与无角色一致 | **需现场** |
| 圆桌单轮完成时间 < 30s（3个角色） | **需现场** |
| 流式输出实时展示（无明显卡顿） | **需现场** |
| PDF 中文无乱码 | ✅（代码层面字体正确） |
| 浏览器刷新后角色配置不丢失 | ✅ |
| Chrome / Edge / Firefox 均正常 | **需现场** |

---

## 5. 发现的问题与建议

| # | 严重度 | 问题 | 建议 |
|---|--------|------|------|
| 1 | 低 | `/tri-mind` 页面文件仍存在，可通过 URL 直接访问 | 删除 `frontend/src/app/tri-mind/` 或添加重定向到 `/chat` |
| 2 | 低 | @mention 解析使用简单正则，自建角色名含特殊字符时可能匹配失败 | 当前 9 个预设角色无此问题；可后续优化 |
| 3 | 信息 | 圆桌会议 session 不持久化（页面刷新即丢失） | 符合当前设计，如需历史回看可后续加 |

---

## 6. 签字区（现场补全）

| 角色 | 姓名 | 日期 | 签字 |
|------|------|------|------|
| 产品确认 | | | |
| 开发确认 | | | |
| 测试确认 | | | |

---

## 7. 联机复测要点

完整 UAT 仍需：**Docker 全栈 + 已配置 LLM + 至少一个含文档的知识库** 下按 `docs/UAT-角色系统与圆桌会议.md` 逐项操作。

重点联机验证：
1. 不同角色问答风格差异（TC-2.3）
2. 圆桌多轮讨论上下文传递效果（TC-5.3）
3. 主持人总结结构化完整性（TC-7.1/7.2）
4. PDF 导出实际效果
