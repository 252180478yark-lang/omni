# 新闻联播图文 PDF 课程包设计

日期：2026-07-10  
状态：已获用户批准  
自动任务：`automation-2`（北京时间每日 07:30、12:30、21:30）

## 1. 背景

现有自动任务会检索前一天《新闻联播》，生成 Markdown 学习稿，并通过本机
`POST /api/v1/notify/message` 向企业微信群机器人发送文字消息。当前缺口是：

- 没有 PDF 课程包。
- 没有累计课程索引。
- 没有可执行的质量硬门。
- 内容没有稳定拆成国内、国际、股市与经济三部分。
- 企业微信通知服务只能发送文字，不能上传 PDF 文件。
- 现有稿件依赖自然语言结构，无法确定性证明“信息没有丢失”。

本设计把自动任务升级为结构化课程流水线。模型负责研究、解释和课程化表达；
程序负责数据契约、信息覆盖、图表、PDF、索引、质量检查和企业微信送达。

## 2. 已确认的产品决策

1. PDF 采用“教材式精读手册”方向，不做报纸式压缩摘要。
2. 每期固定包含：国内新闻、国际新闻、股市与经济新闻。
3. 股市与经济部分以《新闻联播》为主，补充交易所、监管部门、央行、统计局等官方数据；必须标记“节目内容”或“官方补充”。
4. 图文采用教学图解优先：机制图、时间线、关系图、地图和官方数据图；不默认抓取新闻照片。
5. 每日完整 PDF 直接发送到企业微信群，同时发送手机短摘要。
6. 每周日 21:30 在当日晚间最终版之后，发送最近七天的课程索引 PDF。
7. 同一天使用滚动版本：早间 `v1`、午间 `v2`、晚间 `Final`。三个版本都留档，只增不减；课程索引指向 `Final`。
8. 核心质量项失败时自动重试一次，仍失败则拦截成品，只向群里发送异常提醒；轻微问题只记录警告。
9. 页数不设硬上限。正文突出重点，全部有效新闻条目和来源映射放入完整附录，不能为了控制页数删除信息。

## 3. 目标与非目标

### 3.1 目标

- 让用户每天系统学习国内形势、国际形势、股市与经济，而非只看标题。
- 让每条新闻具备事实、背景、影响链、教学图和经营视角。
- 通过完整节目清单与覆盖映射，确定性验证条目覆盖率为 100%。
- 稳定生成中文 A4 PDF，并完成渲染质量检查。
- 维护可检索的长期课程索引。
- 确认 PDF 文件真正被企业微信接受，而不把“已提交”误报成“已送达”。

本设计中“信息不丢失”的可验收定义是：官方完整节目清单中的每个新闻条目都有去向；每个条目涉及的主体、事件、时间、地点、政策名称和关键数字等实质事实，都进入正文或完整附录并保留来源。它不等于逐字转载完整节目文稿。

### 3.2 非目标

- 不提供个股推荐、买卖点或收益预测。
- 不把非官方财经媒体作为必需数据源。
- 不默认抓取、转载或重新分发新闻摄影图片。
- 不因追求固定页数、固定图数或固定篇幅而删除有效新闻条目。
- 不改变其他企业微信通知通道的 Human Gate 策略。

## 4. 总体架构

```text
自动任务触发
  -> 官方来源采集与完整节目清单
  -> 统一事实底稿 course-manifest.json
  -> 国内 / 国际 / 股市与经济课程化组装
  -> 教学图生成
  -> 信息覆盖与质量硬门
  -> ReportLab PDF 渲染
  -> Poppler 渲染检查 + PDF 文本检查
  -> 课程索引更新
  -> 企业微信短摘要 + PDF 文件上传发送
  -> 送达状态落入索引与质量报告
```

核心原则：`course-manifest.json` 是唯一事实底稿。Markdown、PDF、教学图、企业微信摘要、完整附录和课程索引都只能从它派生，禁止各自重新总结一套内容。

## 5. 组件边界

### 5.1 自动任务编排

`automation-2` 继续负责：

- 计算前一天绝对日期和当前课程阶段。
- 联网检索官方来源。
- 生成或增补结构化事实底稿。
- 调用课程包脚本完成验证、PDF、索引和交付。
- 在任务结果中报告版本、页数、条目数、覆盖率、质量状态和企微送达状态。

自动任务不再直接拼接 PDF，也不直接读取 Webhook 密钥。

### 5.2 课程包脚本

新增 `scripts/news_lianbo_course_pack.py`，提供以下子命令：

- `validate`：验证 manifest、完整节目清单、来源、三部分内容和覆盖映射。
- `build`：生成教学图、Markdown、PDF 和质量报告。
- `index`：幂等更新课程索引；周日生成七天索引 PDF。
- `deliver`：调用本机通知服务发送短摘要和 PDF。

该脚本只做薄 CLI。数据模型、质量门、教学图、PDF 渲染和索引分别放在 `app/services/news_course/` 的独立模块中，避免把完整流水线堆进一个脚本。脚本使用 Codex bundled Python，复用 `reportlab`、`pypdf`、`pdfplumber` 和 Poppler。

### 5.3 企业微信通知服务

保留现有文字端点：

- `POST /api/v1/notify/message`

新增文件端点：

- `POST /api/v1/notify/file`

建议请求契约：

```json
{
  "channel": "daily",
  "relative_path": "2026-07-09/2026-07-09-新闻课程-晚间-Final.pdf"
}
```

端点只允许读取 `/app/data/news-lianbo` 下的相对路径，拒绝绝对路径、目录穿越、非 PDF 文件、空文件和超过 18MB 的文件。`docker-compose.yml` 增加以下主机到容器映射：

```text
E:/agent/outputs/news-lianbo -> /app/data/news-lianbo:ro
```

文件发送流程：

1. 从 `WECOM_WEBHOOKS` 按 channel 取 Webhook，但绝不记录完整 URL 或 key。
2. 使用 URL 解析器提取 key，构造群机器人 `upload_media?type=file` 地址。
3. 以 multipart/form-data 上传 PDF，校验 `errcode=0` 和 `media_id`。
4. 向原 Webhook 发送 `msgtype=file` 与 `media_id`。
5. 只有上传和发送都成功时才返回 `ok=true`。

企业微信群机器人文件发送采用“上传文件获得 `media_id`，再发送 file 消息”的两步协议。设计将 PDF 硬上限设为 18MB，为企业微信 20MB 文件限制留出余量。参考：

- 企业微信群机器人配置说明：https://developer.work.weixin.qq.com/document/path/91770
- 腾讯云文件推送示例：https://developer.cloud.tencent.com/article/2225116

## 6. 唯一事实底稿

### 6.1 顶层字段

```text
schema_version
course_id
news_date
phase                 morning | noon | evening
version               v1 | v2 | final
generated_at
main_thread
program_inventory
source_items
sections
keywords
owner_insights
review
coverage
quality
```

### 6.2 完整节目清单

`program_inventory` 必须来自能够代表当天完整节目条目的官方节目页、文字实录或官方节目单。每个条目包含：

```text
item_id
title
category
source_url
source_published_at
official
```

如果无法得到可信的完整节目清单，属于核心质量失败，不能声称“信息完整”。允许自动切换其他央视官方入口重试一次。

### 6.3 来源条目

`source_items` 保存节目条目和官方补充资料：

```text
source_id
source_kind           program | official_supplement
section               domestic | international | market_economy
publisher
title
url
published_at
facts[]
numeric_facts[]       value + unit + period + source_id
```

任何数字都必须通过 `numeric_facts` 携带单位、统计期和来源编号。模型不得在解释段新增数字。

### 6.4 课程条目

每个重点课程条目包含：

```text
lesson_id
source_ids[]
fact_card
background
why_it_matters
impact_chain[]
interpretation
owner_view
visual_spec
```

`fact_card` 只能写来源支持的事实；`interpretation` 和 `owner_view` 必须明确标记为解读或经营推演。

### 6.5 信息覆盖

每个 `program_inventory.item_id` 和每个有效 `source_id` 都必须映射到：

```text
destination           main | appendix
section
lesson_id (optional)
pdf_page (render 后回填)
```

覆盖率计算：

```text
有有效去向的条目数 / 应覆盖条目总数 = 100%
```

任何“无去向”条目都会触发硬失败。正文没有展开的条目必须进入完整新闻条目附录。

## 7. 来源策略

### 7.1 国内新闻

优先 CCTV、央视网、央视频、央视新闻。需要补背景时，使用中国政府网、国务院部门官网、新华社、人民网及地方政府官方来源。

### 7.2 国际新闻

以《新闻联播》国际条目为主。补充时优先外交部、联合国、国际组织和相关国家政府或监管机构官网。事实与“中国关联、产业链影响、后续观察”分开。

### 7.3 股市与经济

以节目经济主线为主，并补充：

- 中国人民银行、国家统计局、证监会、财政部、商务部、外汇局。
- 上交所、深交所、港交所，以及主要海外交易所或指数编制机构的官方收盘数据。
- 内地、港股和主要海外市场的代表性指数；休市或数据暂缺时明确标注，不用媒体估算补空。

本部分只解释数据、政策传导和可能影响，不提供投资建议。

## 8. PDF 内容结构

PDF 采用 A4 纵向教材式布局，典型正文 14-22 页，附录按当天信息量扩展。

1. 封面与学习导航：课程编号、日期、今日总主线、三部分一句话结论、连续观察。
2. 第一部分 国内新闻：政策、民生、科技、产业和地方发展。
3. 第二部分 国际新闻：外交、地缘、国际组织和主要国家动态。
4. 第三部分 股市与经济：节目主线、官方市场数据、宏观数据和政策传导。
5. 老板视角与经营映射：食品调味品、电商、经销商、B2B、外贸和企业经营；无强相关时明确写无。
6. 复盘与答案：关键词记忆卡、自测题、参考答案和下一日观察。
7. 完整新闻条目附录：所有条目、事实摘要、来源、正文页码或仅附录状态。
8. 来源与质量检查：来源清单、节目/官方补充标识、硬门结果、警告和送达状态。

每条重点新闻固定按以下顺序呈现：

```text
事实卡 -> 背景课 -> 为什么重要 -> 影响链 -> 教学图 -> 经营视角
```

## 9. 教学图策略

默认不抓取新闻摄影图片。教学图全部从 manifest 中已核验的结构化事实和数字生成：

- 政策或事件时间线。
- 因果与政策传导流程图。
- 国内、国际关系图。
- 官方数据柱状图、折线图和对比图。
- 机会与风险矩阵。
- 只有具备可靠边界数据时才生成地图；否则使用关系图替代，不手绘地理轮廓。

每张图必须包含：标题、单位、统计期、来源编号和一句图解。图片数量是软目标：通常每期至少 4-6 张；信息量更大时增加，不为凑图重复表达。

## 10. 早中晚版本规则

### 10.1 早间 v1

- 完成三部分总览。
- 建立完整节目清单和 100% 条目去向。
- 生成第一轮教学图、附录、来源与质量页。
- 发送短摘要和早间 PDF。

### 10.2 午间 v2

- 读取早间 manifest 与 PDF，不重新起一套事实。
- 保留 v1 全部内容。
- 为国内、国际、股市与经济中最重要的条目追加深度拆解。
- 重跑覆盖、PDF 和送达检查，发送午间 PDF。

### 10.3 晚间 Final

- 读取午间 manifest，保留 v2 全部内容。
- 追加关键词记忆卡、自测题、答案和下一日观察。
- 生成当日最终 PDF，并作为课程索引正式入口。
- 周日额外生成并发送七天课程索引 PDF。

## 11. 课程索引

课程索引使用 `course-index.json` 作为机器底稿，派生 `课程索引.md` 和每周 `课程索引.pdf`。按 `course_id` 幂等 upsert，重复运行不得新增重复课程。

每条索引字段：

```text
course_id
news_date
main_thread
domestic_topics[]
international_topics[]
market_economy_topics[]
keywords[]
morning_pdfs[]
noon_pdfs[]
final_pdfs[]
source_count
program_item_count
coverage_rate
page_count
visual_count
quality_status
warnings[]
wecom_text_sent
wecom_pdf_sent
```

周日索引 PDF 展示最近七天的主题矩阵、关键词、连续政策线索、国际线索、市场经济线索、质量状态和每期最终 PDF 路径。

## 12. 文件布局

```text
E:/agent/outputs/news-lianbo/
  course-index.json
  课程索引.md
  课程索引-YYYY-Www.pdf
  YYYY-MM-DD/
    course-manifest.json
    morning-v1.md
    morning-v1.pdf
    noon-v2.md
    noon-v2.pdf
    evening-final.md
    evening-final.pdf
    quality-morning.json
    quality-noon.json
    quality-evening.json
    visuals/
```

中间渲染图片使用 `tmp/pdfs/`，最终产物只写入上述输出目录。
正常情况每个阶段只有一个 PDF；只有压缩后仍超过 18MB 时，才使用 `*-part-1.pdf`、`*-part-2.pdf` 等稳定命名分卷，索引中的 `*_pdfs[]` 按发送顺序记录全部分卷。

## 13. 质量门

### 13.1 核心硬门

以下任一失败时自动重试一次；仍失败则不发送成品 PDF：

1. `news_date` 不是前一天，或节目日期不一致。
2. 无法取得可信的完整节目清单。
3. 国内、国际、股市与经济任一部分缺失。
4. 事实或数字缺少来源编号、单位或统计期。
5. 事实、解读、经营推演没有分层。
6. 完整节目条目或有效来源条目覆盖率低于 100%。
7. PDF 无法打开、页数为零、存在空白页、缺字、裁切或重叠。
8. PDF 文本提取缺少任一核心章节或完整附录。
9. 存在 `TODO`、占位符、内部工具 token 或 Webhook 密钥。
10. 任一待发送 PDF 分卷为零字节、大于 18MB，或应发送的分卷缺失。

### 13.2 轻警告

以下问题记录在质量页和索引中，但允许发送：

- 教学图少于建议数量。
- 某市场休市或官方数据尚未发布。
- 老板视角暂无强相关。
- 个别非核心补充来源响应缓慢。

### 13.3 PDF 检查

- 使用 ReportLab Flowables，避免绝对坐标正文导致分页裁切。
- 使用可嵌入的中文字体；字体预检失败时停止渲染。
- 用 `pypdf`/`pdfplumber` 检查页数、核心章节文本和来源附录。
- 用 Poppler 将所有页面渲染为 PNG，检查尺寸、空白页和渲染失败。
- 脚本把全部渲染页组成联系表；自动任务必须对联系表以及封面、三部分首页、附录首页和质量页执行图像检查，并把结果写回质量报告。无法完成视觉检查时不得进入交付阶段。
- 任何重叠、裁切、黑框或乱码属于硬失败。
- 单个 PDF 超过 18MB 时先压缩图片；仍超限则拆成“正文卷 + 附录卷”等多个分卷。分卷只能改变文件边界，不能删除文字、来源、教学图或附录；所有分卷均送达后才算 PDF 送达成功。

质量结果写入阶段级 JSON，并在 PDF 末页以人类可读表格呈现。

## 14. 错误处理与送达语义

### 14.1 采集失败

- 对失败来源重试一次。
- 切换到同级官方来源。
- 无法建立完整节目清单或三部分内容时停止成品发送，并通过 `alert` 通道说明失败项。

### 14.2 构建失败

- manifest 校验失败：不渲染。
- 教学图失败：若正文完整则记轻警告并继续；图造成数据误导时硬失败。
- PDF 渲染失败：重试一次，仍失败则报警并保留 manifest/Markdown/质量报告。

### 14.3 企业微信失败

- 文字摘要、文件上传、文件发送分别记录状态。
- 上传或发送失败时重试一次，先用 `daily`，再用 `alert`。
- 仍失败时保留本地 PDF，并通过可用文字通道说明“PDF 未送达”；禁止记录成功。
- 不持久化临时 `media_id`，不在日志中打印 Webhook URL 或 key。

## 15. 测试设计

### 15.1 单元测试

- manifest schema 与阶段增补规则。
- 完整节目条目去重和 100% 覆盖率计算。
- 数字来源、单位和统计期检查。
- 课程索引幂等 upsert。
- PDF 文件名、相对路径与 18MB 限制。
- 企业微信上传 URL 的安全构造与密钥脱敏。

### 15.2 PDF 测试

- 中文字体和多页排版。
- 三部分章节、完整附录、来源和质量页存在。
- PDF 文本可提取且无核心章节丢失。
- 每页可被 Poppler 渲染，图片非空。
- 超长条目、长链接、表格跨页和大量附录的压力样例。

### 15.3 企业微信测试

- mock 上传成功、上传错误码、超时、无 `media_id`。
- mock 文件发送成功、错误码和重试。
- 路径穿越、非法扩展名、空文件和超限文件被拒绝。
- 一次人工集成测试确认真实群内同时收到短摘要和 PDF 文件。

### 15.4 自动任务演练

使用现有 `2026-07-09-新闻联播-早.md` 作为迁移样例，补齐结构化 manifest 后演练：

1. 早间 v1。
2. 午间 v2 只增不减。
3. 晚间 Final 与索引入库。
4. 周日七天索引 PDF。
5. 核心质量失败时不发送成品。

## 16. 验收标准

1. 自动任务仍按北京时间每日早、中、晚运行。
2. 每个版本均包含国内、国际、股市与经济三部分。
3. 当天官方节目条目和有效补充来源的去向覆盖率为 100%。
4. 早间、午间、晚间版本只增不减，三个 PDF 均留档。
5. 晚间最终版进入课程索引，周日成功生成七天索引 PDF。
6. PDF 包含教学图、完整条目附录、来源和质量检查页。
7. 每个 PDF 分卷小于等于 18MB，所有页面可渲染，核心章节可提取。
8. 企业微信返回文字、全部 PDF 分卷上传和文件发送成功，索引才标记已送达。
9. 模拟核心质量失败时，群里只收到异常提醒，不收到问题成品。
10. 日志、PDF、索引和错误消息均不泄露 Webhook URL 或 key。

## 17. 预期改动范围

- `services/knowledge-engine/app/routers/notify.py`：新增文件通知路由。
- `services/knowledge-engine/app/services/wecom_webhook.py`：集中处理文本、文件上传和文件发送。
- `services/knowledge-engine/app/services/news_course/`：数据模型、质量门、教学图、PDF 渲染和课程索引模块。
- `services/knowledge-engine/tests/test_notify.py`：补文件发送与路径安全测试。
- `docker-compose.yml`：增加新闻课程输出目录的 `:ro` 只读容器映射。
- `scripts/news_lianbo_course_pack.py`：manifest、教学图、PDF、质量门、索引与交付 CLI。
- `services/knowledge-engine/tests/test_news_course_*.py`：课程包单元、PDF、信息覆盖和索引测试。
- `automation-2`：更新提示词，改为生成结构化 manifest 并调用课程包脚本。

改动保持在新闻课程与企业微信通知边界内，不重构无关业务模块。
