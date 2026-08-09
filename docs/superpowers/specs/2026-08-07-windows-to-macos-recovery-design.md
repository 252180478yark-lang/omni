# Windows → macOS Codex、Omni 与数据库恢复设计

## 背景与目标

Windows 备份已下载到 `/Users/yk/Downloads`。Mac 当前并非空环境：`~/.codex` 已有会话、Skills、配置和登录状态；Docker Desktop 中也已有一轮 Omni 数据迁移与运行栈。本次恢复必须合并两端资产、保留当前 Mac 状态，并最终让用户在 Codex 和 Omni 产品界面/API 中看到恢复结果。

成功标准：

1. Mac 当前 Codex 会话保持可用，Windows 旧会话合并后可在历史中找到。
2. Windows Skills 与 MCP 配置经过兼容处理后可被 Mac Codex 加载，不复制 Windows 程序、缓存或认证文件。
3. Omni 使用 Mac 专用 worktree 和 Docker 栈启动，frontend、nginx、video-analysis 与核心依赖正常运行。
4. PostgreSQL 与业务卷的恢复状态经过确定性验证；关键 schema、表和业务记录可查询，并能通过 Omni 页面或 API 实际看到。
5. 所有写入均有迁移前快照或明确回滚路径，不重复导入已恢复的数据。

## 方案选择

采用“分层合并 + 隔离验证”。

- 不采用整体覆盖 `~/.codex`：这会破坏 Mac 当前会话、登录和新版 SQLite 状态。
- 不采用永久双 `CODEX_HOME`：它可以隔离风险，但旧历史需要手动切换，不能满足统一查看需求。
- 不直接转换或挂载 Windows `docker_data.vhdx`：该文件约 129 GB、属于 WSL2 布局，Mac 剩余空间有限，并且已有 PostgreSQL 逻辑备份与卷归档。

## 恢复流程

### 1. 迁移前快照

- 记录当前 Git HEAD、worktree 状态、Docker 容器/卷/镜像清单和 Compose 项目路径。
- 创建 `~/.codex` 的本地只读恢复快照，保留权限、时间戳和文件结构。
- 对目标 PostgreSQL 执行只读基线查询，记录数据库名、schema、表数量、关键表行数与迁移收据。
- 不在快照或日志中输出密钥值；不把备份上传到第三方。

### 2. Codex 历史、Skills 与 MCP 合并

- 从 Windows `.codex` 中只选择用户数据：`sessions/`、`archived_sessions/`、可验证的历史索引、Skills 和配置。
- 会话按稳定会话 ID与内容哈希去重；目标存在同名但内容不同的记录时保留两份并生成冲突清单，不静默覆盖。
- 先在隔离的临时 `CODEX_HOME` 验证旧 SQLite/索引格式；只有结构兼容且可由当前 Codex 读取时才执行受控合并。旧数据库绝不覆盖 Mac 的 `state_5.sqlite`。
- Skills 按目录和文件哈希比较；Mac 已有版本优先，Windows 独有技能复制为候选并验证 `SKILL.md` 与引用资源完整性。
- MCP 按配置表逐项合并，修正盘符路径、反斜杠、`.exe` 命令和环境变量引用。涉及现有凭据的配置只保留键名/引用，不复制明文密钥。
- `auth.json`、Windows `.exe/.dll`、应用包、cache、logs、临时执行状态不迁移。
- 完成后重启/刷新 Codex，通过任务列表、搜索和配置界面验证新旧历史、Skills、MCP 同时可见。

### 3. Omni 源码与运行修复

- 继续使用现有 Mac 专用 detached worktree；保留全部用户未提交改动。
- 按 `omni-feature-development` 建立影响合同，锁定最小修复范围。
- frontend 使用已经补入 `server.ts` 的 Dockerfile 重建镜像，不重复修改该文件。
- video-analysis 将 AI Hub 返回的 null 模型值归一为空字符串，并增加针对性测试；不修改数据库 schema 或公开 API。
- frontend 与 video-analysis 正常后重新启动 nginx；nginx 不单独做绕过性修复。

### 4. 数据库与业务卷恢复验证

数据库验收分四层，不能只以“容器 healthy”判定完成：

1. **恢复来源**：确认运行栈对应 `omni-full-20260612.dump` 的恢复收据、目标卷和源提交。
2. **结构完整性**：查询关键 schema、迁移版本、表/视图数量、约束与扩展，检查恢复日志无失败对象。
3. **数据完整性**：对关键业务表记录总数、时间范围和代表性主键进行只读核验；与恢复基线/收据可比时进行对照。
4. **产品可见性**：通过现有 API/页面读取恢复后的业务数据，至少选择一个可识别记录或统计值，确认不是空库、测试库或新初始化库。

`vol-knowledge_data.tgz` 与 `vol-scout_sessions.tgz` 只在目标卷缺失或校验不通过时恢复。若现有卷已经由前一轮迁移正确填充，保留现状并记录证据，避免重复解包覆盖。

### 5. 最终验收

- Codex：Mac 当前会话仍在；Windows 旧会话可搜索/打开；Skills 可发现；MCP 配置可解析并通过可用性检查。
- Docker：Postgres、Redis、identity、frontend、video-analysis、nginx 及其必要依赖达到预期状态；关键健康端点返回成功。
- Omni：浏览器能打开实际分配的本机入口；至少一个读取路径展示恢复后的数据库业务数据。
- Git：列出本次精确变更、测试命令与退出码；不把迁移密钥或运行时数据提交到仓库。

## 错误处理与回滚

- Codex 合并失败：停止 Codex 写入，使用迁移前快照恢复 `~/.codex`，Windows 原备份保持不变。
- 会话冲突：不覆盖；隔离冲突项并生成清单。
- MCP/Skill 加载失败：禁用单个候选项，不影响现有配置。
- Omni 修复失败：保持项目合同在未完成状态，按本次精确 diff 回退，不处理无关用户改动。
- 数据验证失败：停止在只读诊断阶段，不删除卷、不重新初始化数据库、不重复导入，先定位目标卷、恢复收据或迁移错误。

## 明确不做

- 不复制或运行 Windows Codex/Docker 二进制。
- 不覆盖 Mac 当前认证文件或系统钥匙串。
- 不删除现有 Docker 卷、镜像、容器或下载备份。
- 不把恢复成功简化为“服务能启动”；必须证明数据库数据在产品读取链路中可见。
