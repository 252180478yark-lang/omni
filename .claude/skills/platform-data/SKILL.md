---
name: platform-data
description: 实时取云图/罗盘/抖店三平台真实数据的统一入口。老板问任何平台数据（5A人群/GMV/订单/库存/搜索/体验分/排名等）时，把话术路由到 platform_fetch MCP tool 取真数据。这是数据底座，不做分析（分析交给上层）。
---

# platform-data：三平台实时取数底座

老板用自然话术问数据 → 你解析话术 → 找端点 → 调 `platform_fetch` 取真数据 → 报数。
**只取数不分析**（经营分析是上层功能）。

## 4 步 SOP
1. **解析话术 → 平台**：5A/心智/触点/GTA → yuntu；大盘/GMV/排名/搜索/体验分 → compass；订单/售后/库存/商品/罚款 → doudian
2. **找端点**：`platform_list_endpoints(platform, query=关键词)` 检索目录拿 endpoint key（优先 `verified:true`）
3. **取数**：`platform_fetch(platform, endpoint, params?)`；多端点用 `platform_batch_fetch(requests)`
4. **报数**：把 `result.fields` + 关键 `data` 用中文报给老板，附 endpoint 真路径（来自 `result.url`）便于核对

## 取数前必查登录态
先 `platform_auth_status()`。某平台 `has_cookies:false` → 提示老板去 **/scout 页扫码登录** 该平台（cookies 1~4 天过期）。

## verdict 含义（取数结果里看）
- `PASS` 真数据到手；`PASS_NODATA` 端点通但业务真无数据（不是报错）
- `FAIL_AUTH` cookies 过期/无权限 → 重新登录；`FAIL_404`/`FAIL_DRIFT` 端点漂移 → 换 `platform_list_endpoints` 找替代或上报
- `FAIL_OTHER` 业务码非 0（参数问题）；`EXCEPTION` 网络/JS 异常 → 重试

## 三平台业务码字段（已内置兼容判定，了解即可）
云图 `status` / 罗盘 `st` / 抖店 `code`（404 大写 `Code`）。统一 `code ?? Code ?? status ?? st ?? errno`。

## 与历史 operator skill 的关系
`*-operator` / `*-finder` 是 phase5 历史产物（浏览器手动驱动）。**本 skill + platform_fetch 是官方实时取数入口**，新功能一律走这里。

## 业务上下文（WADAKAN 和田宽）
shop_id=119217266 / aadvid=1805203190148185 / brand_id=11835330 / industry_id=14（食品饮料）。已写进 `catalog/context.json`，参数模板自动填，无需手传。
