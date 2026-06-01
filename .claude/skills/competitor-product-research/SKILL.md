---
name: competitor-product-research
description: 竞品调研（淘宝）。老板说"调研淘宝有机酱油"、"看看淘宝上卖 X 的怎么做的"、"扒一下淘宝 X 竞品"、"对标淘宝 X"、"淘宝竞品调研 X"等，触发两段式 SOP：先 competitor_search 抓前 50 榜单（显示价/月销/主图/链接）+ 相关性过滤给老板挑，老板挑中后 competitor_decompose 对每个商品的主图+详情页拆「卖点/构图/配色/设计/内容」。每步停下等老板反馈。
---

# competitor-product-research：淘宝竞品调研 SOP

这是 `reverse_storyboard`（反推视频）的"竞品镜像"：把**别人淘宝的主图/详情页**拆成
卖点/构图/配色/设计/内容，能反过来喂老板自己的 `selling-point-finder` /
`generate_creative_pack` / brief。

**老板已拍板的范围**：两段式 · 只出 md 报告（不落库）· 搜索页显示价+月销（不逐个抠真到手价）。

## 触发话术 → 参数

| 老板话术 | query | 备注 |
|---|---|---|
| "调研淘宝有机酱油" | 有机酱油 | 标准两段式 |
| "看看淘宝上卖零添加酱油的怎么做的" | 零添加酱油 | 同上 |
| "扒一下淘宝寿喜烧汁竞品" | 寿喜烧汁 | 同上 |
| "对标淘宝 X，重点看详情页" | X | Step 2 时强调详情页（max_detail_images 调大） |

## 三个现实（先跟老板讲清，别让他以为是 bug）

1. **到手价≈显示价**：抓的是搜索页显示价，可能是**券前标价/预估**，不是领券加购后的真到手价（那要登录+加购才算，本流程不做）。
2. **月销常缺**：淘宝很多商品已隐藏月销，拿不到就标 `—`，不是抓漏了。
3. **要登录态 + 选择器可能要调**：淘宝反爬狠，必须先登录（见下）；DOM 偶尔变，第一次抓不到很正常，看 `debug.html_snapshot` 调一轮选择器（老板说过"先调试淘宝"）。

## Step 0：确认 + 登录态

1. 跟老板确认 `query`（要调研的产品词）。平台当前只有**淘宝**（京东后续接）。
2. 直接进 Step 1 调 `competitor_search`。**如果返回 `error: login_required`** → 淘宝还没登录态，告诉老板：
   > 淘宝得先登录（跟你登罗盘/云图一个套路）：在能弹浏览器的环境跑 scout-agent，
   > `POST http://localhost:8009/api/v1/scout/taobao/relogin` → 弹出的 Chromium 里扫码/账密登录淘宝 → 窗口自动关，cookie 落 `sessions/taobao/user_data`。登好再跟我说"继续"。

   登录是**老板手动步骤**，我代不了。

## Step 1：抓榜单 + 过滤（competitor_search）

```
competitor_search(query="有机酱油", top_n=50, platform="taobao", relevance_filter=True)
```

- 跑完把 `result.markdown` 榜单表给老板看（rank/标题/显示价/月销/店铺/链接 + 跳过了几个不相关）。
- 提醒老板：价格是显示价、月销可能缺（见上现实）。
- 让老板**挑要深拆的**（给序号或直接贴链接）。**停下等老板挑**，不要自动往下拆（拆一个烧一次多模态 token）。
- 抓不到时：
  - `login_required` → 回 Step 0 引导登录。
  - `no_items`（登录在但没解析到）→ 告诉老板"淘宝 DOM 变了，看 `debug.html_snapshot` 我调下选择器"，别假装抓到了。

## Step 2：逐个深拆（competitor_decompose）

老板挑好后，把选中的**整条 item 对象**（competitor_search 返的 items 里那几条，带
`main_image_url`）传进去 —— **必须传 `items` 不要只传 item_urls**，这样详情页被反爬挡时能自动退用搜索主图：

```
competitor_decompose(items=[<competitor_search result.items 里挑中的那几条>], focus_product="有机酱油")
```

- 每个商品出一段 markdown：**卖点 / 构图 / 配色 / 设计 / 内容** + 一句话打法 + 借鉴/避开。
- **详情页现实（自动 A）**：tool 先试**移动 H5 详情页滚动截图**喂视觉模型；淘宝详情页反爬最狠，被挡时（"访问被拒绝"/验证码）**自动退用搜索主图**拆（卖点/构图/配色/设计照出，第 5 节"内容"标"详情页被挡仅主图"）。如实告诉老板，别假装拆了详情页。
- **要真详情页（手动 B，100% 可靠）**：让老板在自己手机/电脑淘宝里截几张详情页图，存到挂载目录（桌面在 KE 里是 `/host/Desktop/xxx.jpg`），然后 `competitor_decompose(local_images=["/host/Desktop/xx.jpg", ...], focus_product="有机酱油")` —— 真实登录态截的图没反爬，5 维全出。老板也可直接把截图贴给我，我直接按 5 维度拆。
- 把 `result.markdown` 整篇给老板。有 `errors` 如实说哪个没拆成。
- 老板要更深 → 重跑 `model="gemini-3.1-pro-preview"`。一次最多 12 个（防烧 token），多了分批。

## Step 3（可选）：喂回自己的内容引擎

老板说"照这个思路给我自己的 SKU 也来一套"时：
- 把竞品拆解结论塞进 `selling-point-finder` / `generate_creative_pack(extra_context=...)` 当参考，
  生成老板**自己 SKU** 的卖点/素材。**注意**：竞品的卖点是参考，不能直接当自己 SKU 的事实抄
  （别把竞品的"零添加""有机认证"安到没这资质的自家货上——犯反幻觉铁律）。

## 通用约束（跟其他 omni skill 一致）

- **每步停下等反馈**，尤其 Step 1→2 之间必须等老板挑（烧钱步）。
- **带来源**：拆解每条标依据哪张图；榜单标显示价/月销缺失。
- **说人话**，禁 AI 化套话（赋能/打通/闭环/抢占心智/极致/匠心/一站式）。
- **反幻觉**：图里没有的卖点/资质/数据不许编（competitor_decompose 的 prompt 已硬约束，输出里若发现编造，叫停重跑）。
- 只出 **md 报告**，不落 DB（老板拍板）。老板要存就自己存 md。

## 错误处理速查

| 现象 | 多半是 | 怎么办 |
|---|---|---|
| `login_required` | 没登录/登录态过期 | Step 0 引导老板 relogin 淘宝 |
| `no_items`（登录在） | 淘宝搜索页 DOM 变了 | 看 `debug.html_snapshot`，调 `taobao.py` 的 `_SEARCH_EXTRACT_JS`，`docker restart omni-scout-agent` |
| `no_images_fetched` | 详情页 DOM 变/跨域 iframe | 看 `debug.screenshot`，调 `_DETAIL_EXTRACT_JS` |
| `scout_unreachable` | scout-agent 没跑 | `docker ps` 看 omni-scout-agent，没起就 `docker compose up -d scout-agent` |
| `browser_failed`（headless） | 容器内开了非 headless | 传 `headless=True`，或在 host 跑 scout-agent |

## 跟 CLAUDE.md / 其他 skill 的关系

- 工具实现见 CLAUDE.md「竞品调研」节：`competitor_search` / `competitor_decompose`（KE）+ scout-agent `/taobao/*` 端点。
- 跟 `video-reverse` 同源思路（拆解媒体→结构化），区别：那个拆视频喂自己出片，这个拆竞品图找对标。
