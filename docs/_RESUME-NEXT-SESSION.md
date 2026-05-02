# 🎯 下次会话恢复指南

> **作用**：任何 Claude 会话加载这个仓库后，读这一份文档即可了解状态并接着干。
>
> **更新于**：2026-05-02 v2.0（**32 天施工 Week 1-5 全部完成**：scout-agent 全栈实现，前端四页面接线，等待三平台扫码登录即可试运行）

---

## 一、我们在哪儿（30 秒看完）

```
路径 A 抖店 MVP                    路径 B 中台底座
┌─────────────────────┐           ┌─────────────────────┐
│ 4 份文档 ✅           │          │ 4 份文档 ✅          │
│ 桥接代码 ✅           │          │ （未启动施工）       │
│ 数据源 1 罗盘 ✅      │          └─────────────────────┘
│ 数据源 2 抖店后台 ✅  │
│ 数据源 3 云图 ✅      │
│ §13.4 修订建议 ✅     │
│ 4 份正式文档已刷新 ✅ │
│   ↓                  │
│ 老板填 SKU 🚧         │
│   ↓                  │
│ 32 天施工（未启动）   │
└─────────────────────┘
                    ↓
              当前停在这里：
              所有文档准备就绪；
              等老板提供 5 个真实 SKU 商品 ID + 企微 webhook
              然后启动 32 天施工
```

**简言之**：3 平台调研 + 4 份正式文档（01-PRD / 02-施工 / 03-验收 / 04-使用指南）全部刷新完成（v1.4），所有设计已就绪。**下一步等老板提供 5 个 MVP SKU 商品 ID + 企微 webhook URL，然后即可启动 32 天施工**。

---

## 二、为什么要先调研（避免之前我犯的错）

之前我直接选了"4 份罗盘报表"做路径 A 抓取范围，老板（用户）指出**这是凭直觉跳到结论**。正确顺序：

```
① 穷举数据源（抖店生态有哪些可看？）
   ↓
② 筛选数据维度（哪些真值得每天看？）
   ↓
③ 反推动作清单（哪些动作可能影响这些数据？）
   ↓
④ 选 MVP 范围（这次抓什么 + 让用户登记什么）
```

调研完成后会**回过头微调**：
- `01-PRD-抖店MVP产品需求文档.md` §1.5 范围 / §4.1 抓取范围
- `02-施工-抖店MVP工程实施文档.md` 数据模型 `change_event.asset_type` 枚举
- 罗盘调研后已敲定 5 份 runbook（A/B/C/D/E），见 §13.4.1

---

## 三、调研协作方式（重要）

文档骨架在：`docs/路径A-抖店MVP/00-调研-抖店数据与动作全景.md`

### 用户这边：
- 一次打开**一个**数据源（比如先开抖店罗盘）
- 告诉 Claude：
  1. 顶层菜单都有哪些（截图 / 口述）
  2. 你**每天/每周**会点开哪些菜单
  3. 那些页面里你**重点看什么字段**
  4. 是否能**导出**（CSV / Excel / 截图）
- 可选：告诉 Claude 你在这个平台**做过哪些动作**（帮补充动作类型清单）

**截图怎么传给 Claude Code**（终端不能直接粘）：
1. 截图保存到 `docs/路径A-抖店MVP/screenshots/`，命名 `{数据源}-{序号}.png`（如 `罗盘-01.png`）
2. 在对话里说："看 screenshots/罗盘-01.png" → Claude 用 Read tool 读图
3. 详见 `screenshots/README.md`，已设好 .gitignore 忽略

### Claude 这边：
- 实时把用户描述写入 00-调研文档对应章节
- 每完成一个数据源 → 给用户小结让他确认
- 9 个数据源全部完成后 → 出汇总章节（§11/§12/§13）→ 给路径 A PRD 修订建议

---

## 四、3 个待调研数据源（已收口）

> **2026-05-02 老板决策**：MVP 收口至**抖店后台 + 抖店罗盘 + 巨量云图**这 3 个平台。
> 千川 / 百应 / 算数 / 飞瓜 / 蝉妈妈 / App 内观察均**移出 MVP**（v2 再说）。

| 顺序 | 数据源 | 路径 | 重要性 | 状态 |
|---|---|---|---|---|
| 1 | 抖店罗盘 | https://compass.jinritemai.com/ | ⭐⭐⭐⭐⭐ | ✅ 已完成（2026-05-02，83 张截图） |
| 2 | 抖店后台 | https://fxg.jinritemai.com/ | ⭐⭐⭐⭐⭐ | ✅ 已完成（2026-05-02，19 张截图） |
| 3 | 巨量云图 | https://yuntu.oceanengine.com/ | ⭐⭐⭐⭐ | ✅ 已完成（2026-05-02，26 张截图） |

**3 平台调研已全部完成**（详见 `docs/路径A-抖店MVP/00-调研-抖店数据与动作全景.md` §1 / §2 / §3 / §11 / §13）：

**三视角分工**：
- **罗盘 = 看 + 诊断 + 排名**（店铺数据视角）→ GMV/UV/客单/退款率/体验分/客服分析/搜索/榜单
- **抖店后台 = 做动作 + 管订单**（店铺动作视角）→ SKU 主数据/库存变更记录/物流诊断/评价管理/6 待办数/营销活动
- **云图 = 品牌资产视角**（最重要的差异化视角）→ 5A 资产 6 卡/6 场景流转/品牌心智 3 指标/GMV TO 5A 归因/触点效能

**主线指标**："**用户支付金额**"（不是 GMV、不是成交金额）

**双 benchmark**：
- 罗盘：行业均值 / 优于同行 X%
- 云图：对比品牌均值 / 行业排名（如 1732 ▼ 35）

**收口结果**（v1.4 终版）：
- **runbook 8 份**：A 全店日报 / B SKU 详情 / C 客服与原声 / D 搜索与流量与营销 / E 人群与机会 / F 物流与履约 / **G 品牌心智** / **H 品牌资产/触点效能**
- **工期 32 天 / 约 4.5 周**（罗盘 12 + 抖店后台 7 + 云图 8 + 跨平台合并 3 + buffer 2）
- **`change_event.asset_type` 12 类**（加 user_reach + brand_strategy）
- **`change_event.source` 4 类**：user_manual / shop_admin_log / compass_log / yuntu_log
- **动作日志双轨**：用户登记（轨 A）+ 平台被动抓取（轨 B），互相校验
- **新表**：`mvp_stock_change_log` / `mvp_5a_asset_daily` / `mvp_5a_flow_daily` / `mvp_industry_benchmark`
- **千川 / 联盟 / 算数 / App / 飞瓜 / 蝉妈妈** 全部移出 MVP；部分功能由云图触点效能 / 罗盘渠道占比 / 罗盘榜单替代

如有用户补充的来源（内部 ERP / Excel / 企微小工具等），加到第 10、11…

---

## 五、调研完成后接下来的工作

### Phase 1：调研收尾 ✅ 全部完成
- [x] 数据源 1 罗盘 ✅（2026-05-02）
- [x] 数据源 2 抖店后台 ✅（2026-05-02）
- [x] 数据源 3 巨量云图 ✅（2026-05-02）
- [x] 3 平台数据合并 → 终版 §11 / §12 / §13 ✅
- [x] 输出对路径 A PRD 的精确修订建议 ✅（v1.4，详见 §13.4）

### Phase 2：路径 A PRD 落地 ✅ 全部完成
- [x] 罗盘部分修订建议已写入 `00-调研` §13.4（2026-05-02）
- [x] 抖店后台部分修订建议已写入 `00-调研` §13.4（2026-05-02 v1.3）
- [x] 云图部分修订建议已写入 `00-调研` §13.4（2026-05-02 v1.4 终版）
- [x] **实际写入 `01-PRD` §1.5 / §4.1**（8 份 runbook + 32 天工期 + 13 类异动检测规则）
- [x] **实际修订 `02-施工` 数据模型**（12 类 asset_type / 4 类 source / 5 张新表：mvp_stock_change_log + mvp_5a_asset_daily + mvp_5a_flow_daily + mvp_brand_mind_daily + mvp_industry_benchmark / mvp_sku 字段扩展 / mvp_daily_metric 字段扩展 / 32 天 ticket 列表 T01-T59）
- [x] **实际修订 `03-验收`**（V01-V11 各加抖店后台/云图 sub-case + V11-V23 v1.3/v1.4 增补验收项 + 13 条异动规则覆盖）
- [x] **实际修订 `04-使用指南`**（12 大类动作 + 双轨说明 + 4 标记 👤🏪☁️🌐 + 6 场景化策略卡 + 四视图协作流 + 5A 心电图 + 6 待办数 + Q1b/Q1c FAQ + 术语表 v1.4）

### Phase 3：v1.5 老板输入零阻塞 ✅
- [x] ~~选 5 个 MVP SKU~~（v1.5 删：sku_bootstrapper 自动同步全店 41 SKU）
- [x] ~~给研发抖店商品 ID~~（v1.5 删：focus_pool_builder 自动选重点池）
- [x] ~~申请企微 webhook~~（v1.5 改：可选，任意时刻补到 .env 即生效；默认走站内通知）
- [x] 确认品牌设置：WADAKAN/和田宽（食品饮料）— 已默认配置
- 老板**唯一阻塞输入** = 三平台扫码登录（约 5 分钟，§04-使用指南 §1.2）

### Phase 4：路径 A **32 天**施工（按 02-施工文档，v1.4 终版，约 4.5 周）
- [x] Week 1：scout-agent 框架 + 数据底座 ✅（FastAPI :8009 + Playwright + DB pool + 15 mvp_* 表 + 通知多渠道）
- [x] Week 2：罗盘相关抓取 ✅（12 个 compass runbook：首页/交易/商品/体验分/客服/用户原声/搜索/物流）
- [x] Week 3：抖店后台抓取 ✅（8 个 shop-admin runbook：待办/SKU/库存/诊断/评价/物流/会员/营销）+ 双轨合并器
- [x] Week 4：云图抓取 ✅（6 个 yuntu runbook：首页总览/5A资产/5A流转/品牌心智/触点效能/GMV归因）
- [x] Week 5：8 份 runbook suite（A-H）+ APScheduler（5 定时任务）+ 前端四页面（workspace/products/sku/scout）+ API 代理层
- **施工完成**：运行 `python scripts/apply_migrations.py` + 三平台扫码登录 + 启动 scout-agent 即可试运行

### Phase 5：MVP 上线 + 7 天稳定性测试
- [ ] 老板三平台扫码登录（约 5 分钟，/scout 页面点「扫码」）
- [ ] 运行 `python scripts/apply_migrations.py`（迁移 009 + 010）
- [ ] 启动 scout-agent（`docker-compose up scout-agent` 或本地 `uvicorn app.main:app --port 8009`）
- [ ] 手动触发 Runbook B（B-SKU详情），验证 SKU 自动同步到 /products 页
- [ ] 手动触发 Runbook A（A-全店日报），验证指标写入 + 异动检测
- [ ] 验收（按 03-验收文档 V01-V26）

### Phase 6：路径 B 启动（4-6 周）
- [ ] 数据迁移 mvp_* → omni_*
- [ ] sidebar 7 项重构
- [ ] 天猫/京东接入
- [ ] SKU 详情 7 Tab
- [ ] Dashboard / 决策中心完整版

---

## 六、关键设计共识（已锁定，不要再讨论）

> 以下是已经 agreed 的设计原则，新会话恢复时不要重新挑战这些。

1. **3 层底座 + 4 条使用流** 是中台心智模型
2. **SPU + platform_instance 双层抽象**：底层数据统一，上层视图分平台 + 全景双视角
3. **抖店优先**（用户最熟），天猫/京东留给路径 B Week 3-6
4. **mvp_\* 临时表 → omni_\* 正式 schema** 严格父子集，迁移零损失
5. **决策日志强制落库**：所有 AI 输出都有持久身份（roundtable/chat/scout/manual_diagnosis 一律）
6. **"Send to..." 跨模块流转**机制
7. **Focus Context** 工作焦点
8. **AI 不自动执行动作**（路径 A/B 都不开），只给建议+用户采纳
9. **强制登记动作**才能跑通飞轮（极简表单 ≤60 秒）
10. **一次只动一个变量**才能干净归因（系统会鼓励错峰）

---

## 七、桥接代码（已就位，TypeScript 0 错误）

```
frontend/src/components/app-sidebar.tsx        sidebar 5 段重排
frontend/src/app/workspace/page.tsx            工作台占位
frontend/src/app/products/page.tsx             产品列表（5 占位 SKU）
frontend/src/app/sku/[id]/page.tsx             SKU 详情 3 Tab 框架
frontend/src/app/scout/page.tsx                巡店监控占位
frontend/src/app/decisions/page.tsx            决策日志中心（已可用）
frontend/src/stores/decisionStore.ts           zustand + persist
frontend/src/components/save-to-decision-button.tsx  共享按钮
frontend/src/app/chat/page.tsx                 已接入按钮
frontend/src/components/roundtable-view.tsx    已接入按钮
```

**localStorage key**：`omni-decision-log-v1`

---

## 八、新会话开机命令

如果你（老板）下次想直接说"继续"，新 Claude 应该这样反应：

1. 读 `MEMORY.md` 索引（项目级 memory）
2. 读 `docs/_RESUME-NEXT-SESSION.md`（本文档）
3. 读 `docs/路径A-抖店MVP/00-调研-抖店数据与动作全景.md`（看调研进度）
4. 告知用户："3 平台调研 + 4 份正式文档（01-PRD/02-施工/03-验收/04-使用指南）全部刷新完成（v1.4）。下一步等你提供 5 个真实 MVP SKU 商品 ID + 企微 webhook，然后启动 32 天施工。"
5. 用户提供 SKU + webhook → Claude 触发施工启动（按 02-施工文档 T01-T59 ticket 列表）

---

## 九、快速 FAQ（恢复时可能的疑问）

### Q：为什么不在 8 份文档里直接定数据源就开干？

A：用户在 2026-04-30 中明确指出"先选 4 份罗盘报表"是错误的设计顺序——会漏掉抖店生态的其他重要数据源（千川/百应/云图/客服后台等），也会漏掉相应的动作类型。需要**先穷举后筛选**才不会返工。

### Q：路径 A 的 14 天工期会变吗？

A：v1.4 终版工期 = **32 天 / 约 4.5 周**（3 平台调研全部完成后）：
- 罗盘相关：12 天
- 抖店后台相关：7 天（41 SKU + 库存变更记录 + 物流诊断 3 Tab + 评价管理 4 Tab）
- 云图相关：8 天（5A 资产 + 5A 流转 + 品牌心智 + 触点效能 + 商品 4 Tab + GMV TO 5A 归因）
- 跨平台数据合并 + benchmark 字段融合：3 天
- buffer + 联调 + 反爬测试：2 天

千川已移出 MVP，部分功能由云图触点效能替代。

### Q：8 份文档已经写完了，调研后大改吗？

A：**不大改**。架构、数据模型、决策日志、动作日志的整体框架已经足够通用。调研主要影响：
- 路径 A 抓取范围（哪些 runbook）
- `change_event.asset_type` 枚举值（哪些动作类型）
- `daily_metric.metric_name` 枚举值（哪些指标）
- 使用指南的具体步骤示例

### Q：路径 B 也要等吗？

A：路径 B 设计已就绪，但**正式启动要等路径 A MVP 验证使用习惯成立后**（约 2-3 周）。两条路径不重叠施工。

---

**最后更新**：2026-05-02 by Claude（**v2.0 施工完成** · 34 个 runbook · 14 项 Python 服务 · 4 个前端页面接线 · 2 个 DB 迁移 · APScheduler 5 任务 · 双轨合并器）

---

## 十、施工产物速查

| 层 | 文件 / 路径 | 说明 |
|---|---|---|
| DB | `migrations/009_mvp_tables.sql` | 15 张 mvp_* 表 |
| DB | `migrations/010_dual_track.sql` | 双轨合并列 + mvp_merge_run 表 |
| 服务 | `services/scout-agent/` | FastAPI :8009 主体 |
| Runbook | `runbooks/compass/` (12) | 罗盘 12 个子 runbook |
| Runbook | `runbooks/shop-admin/` (8) | 抖店后台 8 个子 runbook |
| Runbook | `runbooks/yuntu/` (6) | 云图 6 个子 runbook |
| Runbook | `runbooks/runbook-suite/` (8) | A-H 套件 runbook |
| 服务 | `app/services/dual_track_merger.py` | 双轨动作日志合并器 |
| API | `app/routers/skus.py` | SKU / 动作 / 决策 REST API |
| 前端代理 | `frontend/src/app/api/omni/scout/` | catch-all Next.js 代理 |
| 前端页 | `frontend/src/app/workspace/page.tsx` | 工作台（接线 scout API） |
| 前端页 | `frontend/src/app/products/page.tsx` | 产品列表（接线 scout API） |
| 前端页 | `frontend/src/app/sku/[id]/page.tsx` | SKU 详情（3 Tab 实时数据） |
| 前端页 | `frontend/src/app/scout/page.tsx` | 巡店监控（Runbook 控制台） |
