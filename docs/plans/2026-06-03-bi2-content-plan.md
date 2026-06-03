# 全量 BI 2.0 数据全景呈现规划（2026-06-03 · workflow 遍历三平台 204 verified 端点产出）

> 老板验收觉得「数据不全」。本规划遍历三平台 491 端点中 **204 个已验证真出数**的，分类判定哪些该上 BI、归哪个主题/视角、配什么图表。

## 总览

三平台分工清晰：罗盘=经营+流量+搜索+达人+竞品的「店内真账」，云图=5A人群资产+品牌心智+行业对标的「人群+赛道镜子」，抖店=履约/售后/体验/资金的「后端健康」。把 204 个端点剔掉 ~90 个纯配置/会话/写操作/重复后，真正 bi_worthy=high/med 的约 60 个，可拼成一张完整图景：老板面=经营大盘(GMV趋势+目标达成)→行业排名/市占率→体验分/服务健康→品牌心智/口碑；操盘手面=转化全链路漏斗(曝光-点击-成交+流失定位)→流量来源结构→搜索表现对标→人群5A资产+八大人群+触点蓄水→货品结构+商品榜+价格带→达人/直播带货→千川投放ROI。现状底座已接 22 端点（经营大盘/per-SKU商品/价格带占比/八大人群5A/达人榜/搜索词/流量来源/畅销榜全落库），覆盖了「看见数据」的骨架。最大缺口集中在四块：①转化漏斗的「流失定位」与「流量来源5源排行」（漏斗有了但流失环节、enter_source、flow_source_detail 没接）②搜索表现的四档行业对标(overview_data)+实时热词(机会分)③千川投放ROI榜(core_index_v3)——目前完全没有「投钱回报」维度④云图品牌心智/市占率/NSR口碑/品牌直播间对标 一整块行业镜子没接。现状是「店内自家数据较全，但缺投放回报+行业对标+品牌资产」三大块，所以老板感觉「数据不全」。

## 主题全景（16 个，按优先级）

| 优先级 | 主题 | 视角 | 能呈现 | 关键指标 | 图表 | 覆盖 | 端点(★已接) |
|---|---|---|---|---|---|---|---|
| P0 | 经营大盘(北极星) | boss | 老板每天第一眼：今日GMV、同环比、目标达成进度、店铺等级。一条折线+几张KPI卡看店有没有异动、大促打得怎么样。 | gmv_paid日趋势,同比环比,buyer_count,GMV目标达成度,店铺等级,GTA月度GMV同环比 | KPI卡,折线,达成进度环 | 部分(核心趋势★已接;homepage今日大盘/GTA月度目标/店铺等级未接) | compass.core_trend_v3★,doudian.homepage,yuntu.getaudiencegtaprofile,compass.core_index,doudian.getcompassdiagnosis |
| P0 | 行业排名与市占率(赛道位置) | boss | 老板第二眼：我在这条赛道排第几、占多少份额、排名涨跌。一组KPI卡回答「我是不是在掉队」。 | 店铺7日行业排名,排名涨跌,同行店铺数,品牌市占率%,行业联想排名 | KPI卡(排名+环比+市占率%) | 部分(industryrank/corebrand★已接;shop_rank店铺排名/市占率insightbrandoccupancy未接) | compass.shop_rank,yuntu.insightbrandoccupancy,yuntu.industryrank★,yuntu.getoverview,yuntu.corebrand★ |
| P0 | 转化全链路漏斗+流失定位 | both | 操盘手最关键的一张图：曝光→点击→成交全链路漏斗，配各环节流失量/流失率，一眼定位「转化卡在哪一层、流量在哪步漏掉」。这是诊断的核心。 | 曝光人数,点击人数,成交人数,曝光支付转化率,各环节流失量/流失率,商品卡UV价值 | 漏斗,KPI卡(流失率) | 部分(漏斗★已接;关键的flow_loss_card流失定位/flow_overview_card流量大盘/core_data UV价值都未接) | compass.flow_source_funnel★,compass.flow_loss_card,compass.flow_overview_card,compass.core_data |
| P0 | 人群5A资产+八大人群+触点蓄水 | both | 云图核心资产：5A各层(A1-A5)人数走势、自家vs行业TOP20对标、八大人群占比、A1触点蓄水来源(视频vs直播)、5A层间流转同环比。回答「种草资产够不够厚、A2→A3卡没卡、靠啥触点蓄的水」。 | A1-A5资产人数及30天走势,5A vs行业TOP20对标,八大人群占比,A1触点蓄水(视频/直播),5A层间流转同环比,A3净流入率 | 5A分层堆叠,多线折线,人群堆叠柱,饼(触点),桑基/流转图 | 已接为主(5A趋势/结构/流转/八大人群★全已接;缺触点蓄水分布+种草场景流转桑基图) | yuntu.get_audience_asset_trend★,yuntu.getaudienceassetstructure★,yuntu.audienceflowanalysisv2★,yuntu.getaudienceassetbig8profile★,yuntu.getaudienceassetbig8trend★,yuntu.get_audience_asset_trigger_point_distribution,yuntu.audienceflowsceneanalysisv2 |
| P0 | 货品结构+商品榜 | operator | 操盘手选品：自家货品GMV占比(爆款/常规品健康度)+per-SKU商品榜(哪个规格卖得动/要补货)+行业畅销榜(看赛道爆款选品)。 | 爆款GMV占比,常规品GMV占比,per-SKU支付额/库存/环比,行业畅销商品GMV排名 | 饼(货品结构),榜单表,折线(单品流量趋势) | 已接(货品结构/per-SKU/商品榜/行业畅销/单品趋势★全已接,这块最完整) | yuntu.productstructure★,compass.sku★,compass.product_list★,yuntu.bestsellingproduct★,compass.trend_v3★ |
| P0 | 服务体验+口碑健康 | boss | 店铺健康红线：体验分(总分+商品/物流/服务子分)+行业对比、好评率/差评数、负面问题分类排行、平台罚单、品牌NSR净推荐口碑(正中负声量)。老板盯「体验分掉没掉、客户在骂啥」。 | 体验分及3子分,好评率,差评数,负面问题分类排行,平台罚单,NSR正/中/负占比 | KPI卡,榜单表(负面问题),堆叠(NSR) | 部分(体验分★已接;好评率statistics/负面问题排行/罚单/NSR口碑/prof_exp_score行业对比都未接) | doudian.getoverviewbyversion★,compass.prof_exp_score,doudian.statistics,compass.shop_negative_problem,doudian.get_ticket_list,yuntu.getbrandnsrdetailstats |
| P1 | 流量来源结构 | operator | GMV从哪个渠道来：5大流量源排行(各源曝光/点击/支付)+入口成交占比。看是吃自然流量、付费、还是达人，是不是过度依赖单一渠道。 | 5大流量源支付人数排行,各入口GMV占比,商品卡分时段来源,各源曝光/点击 | 榜单表,饼/堆叠,柱 | 部分(flow_data_v2★竞品流量已接;自家flow_source_detail_v2 5源排行/flowentrystructure入口占比/enter_source未接——这是大缺口) | compass.flow_source_detail_v2,yuntu.flowentrystructure,compass.enter_source_v2,compass.flow_data_v2★ |
| P1 | 商品5A漏斗(种草到成交) | operator | 单品维度的5A漏斗：某商品A1→A4各层人数+层间转化率，看具体哪个品种草到成交哪一层断了。比店铺级漏斗更细，直接指导单品打法。 | 商品A1-A4人数,层间转化率,带货矩阵5A覆盖 | 漏斗,柱(蓄水1天vs15天成交) | 未接(单品5A漏斗整块没接,是连接人群资产与商品的关键诊断) | yuntu.getproductoverview5aanalysis,yuntu.sellmatrix,yuntu.getspucontribution |
| P1 | 价格与选品(定价该卡哪档) | both | 调味品类目各价格带的GMV占比/销量占比/在售店铺数，配价格带直方图看定价该卡哪个价位带、哪档拥挤哪档蓝海。 | 各价格带GMV占比,销量占比,在售店铺数,类目占比最高价格带 | 价格带直方图 | 部分(占比中值★已接但是headline标量;完整9档分布需价格带直方图组件——图表组件缺) | compass.category_overview_price_band_distribution★ |
| P1 | 搜索表现+对标+热词机会 | both | 搜索渠道全景：搜索GMV趋势+周环比、自家vs行业基准/优秀/顶尖四档对标、本店搜索排名、引流词→商品下钻、实时热词机会分、待优化商品。回答「搜索这条路打得怎么样、该抢哪些词」。 | 搜索GMV趋势,周环比,四档行业对标,搜索排名,引流词榜,实时热词机会分,待优化商品 | 折线,柱(四档对标),榜单表,下钻树 | 部分(搜索GMV趋势/引流词★已接;关键的四档对标overview_data/实时热词机会分/待优化商品/搜索排名都未接) | compass.overview_data_trend★,compass.overview_data,compass.weekly_report_summary,compass.shop_rank_1,compass.word_rank★,compass.realtime_word_overview_v2,compass.recommend_optimized_product_v2,yuntu.listindustrydiscoverkeywordstats |
| P1 | 达人/直播带货 | operator | 达人渠道：合作达人历史榜(粉丝/GMV/合作次数)、Top直播间GMV榜、抖音号带货销量榜、自家品牌直播间表现(GMV/GPM/转化)vs行业Top、达人同层对比。看「找谁带货带得动、自播打得过同行不」。 | 达人GMV/累计GMV/合作次数,Top直播间GMV,抖音号带货GMV,自播GMV/GPM/转化率vs行业Top,达人同层领先比例 | 榜单表,KPI卡(自播vs行业),柱(同层对比) | 部分(达人历史榜★已接;Top直播间/抖音号带货榜/品牌自播对标getbrandaccountliveoverview/达人同层对比都未接——需达人榜组件) | compass.list★,compass.top_list,yuntu.bestsellingauthor,yuntu.getbrandaccountliveoverview,compass.card_list,yuntu.getbrandaccountliveroommetrics |
| P1 | 投放ROI(千川·广告) | operator | 全盘唯一的「投钱回报」维度：各商品千川消耗与ROI排行，看投钱投在哪个品上回报最高。当前BI完全没有这块,是操盘手做预算分配最缺的一张表。 | 各商品千川消耗,ROI排行,广告投产比 | 榜单表 | 未接(完全空白,无任何投放回报数据;操盘手最痛的缺口之一) | compass.core_index_v3 |
| P2 | 品牌心智(消费者怎么记住你) | boss | 云图品牌资产软指标：心智关联人数+行业排名、Top关联词及趋势、AI口碑总结。回答「消费者一提调味品想不想得到你、记住的是啥关键词」。 | 心智关联人数,行业联想排名,Top心智关联词及趋势 | KPI卡,榜单表+迷你趋势 | 未接(品牌心智整块没接,偏长期资产,锦上添花) | yuntu.getoverview,yuntu.listbrandtopkeyword,yuntu.get_summary |
| P2 | 竞品与行业洞察 | both | 扒对手与看赛道：竞品爆款流量结构、同类竞品清单(标题/主图/价格带)、行业大盘概览/趋势、品牌分布份额、细分市场SPU排名对比。给选品和差异化定位做参考。 | 竞品流量结构,同类竞品价格带,行业GMV/增速,品牌份额分布,细分市场SPU排名 | 堆叠,榜单表,折线,饼 | 部分(corebrand品牌榜/flow_data_v2★已接;同类竞品清单/行业大盘/趋势/品牌分布未接) | compass.flow_data_v2★,compass.good_compete_product_list,yuntu.marketoverview,yuntu.trendinsights,yuntu.branddistribution,yuntu.insightproductstats,yuntu.corebrand★ |
| P2 | 物流履约健康 | operator | 履约后端：今日各订单状态计数、履约诊断(拒签率/退货回传率)、各物流线路准时率排行。看「发货顺不顺、哪条线爱晚点」。 | 各订单状态计数,拒签率,退货物流回传率,各线路准时送达率 | KPI卡,榜单表(线路准时率) | 未接(履约整块没接,运营后端健康度,锦上添花) | doudian.tabcnt,doudian.getdiagnosisconclusion,doudian.getlogisticsdiagnosislinearriveontimeratelist |
| P2 | 售后退款 | operator | 售后压力：今日待处理售后单数、差评原因分类。看「售后忙不忙、退款主要为啥」。 | 待处理售后单数,差评原因分类 | KPI卡,榜单表 | 未接(售后计数没接,锦上添花) | doudian.counts,compass.shop_negative_problem |

## 老板面 BI 板块

老板面(经营诊断,按重要性排)：①经营大盘头条带——今日GMV+同环比+目标达成度+店铺等级(P0,KPI卡+折线)，一眼看店有没有异动。②行业位置卡——7日行业排名+排名涨跌+品牌市占率%(P0,KPI卡)，回答「在不在掉队」。③服务健康红线——体验分(总+3子分)+好评率+差评数+负面问题Top(P0,KPI卡+榜单)，盯红线别踩。④转化漏斗缩略——曝光→点击→成交+总转化率(P0,小漏斗)，看大盘转化效率。⑤人群资产厚度——5A总资产趋势+vs行业TOP20对标(P0,折线+堆叠)，种草资产够不够。⑥搜索周报——搜索GMV周环比+四档对标(P1,KPI卡)。⑦品牌心智+NSR口碑(P2,折线/堆叠)，长期资产。设计原则：老板面只看「结论性指标+异动报警+对标差距」，不堆操盘手的明细榜，每块配一个「下钻看详情」入口转操盘手面。

## 操盘手面 BI 板块

操盘手面(投放选品诊断,按重要性排)：①转化全链路漏斗+流失定位——曝光-点击-成交全链路+各环节流失量/流失率(P0,漏斗+流失KPI)，诊断核心，定位卡在哪层。②人群5A资产盘——A1-A5趋势+八大人群占比+A1触点蓄水+5A层间流转同环比(P0,多线折线+人群堆叠+桑基)，看种草盘子+A2→A3卡点。③货品结构+商品榜——货品GMV占比饼+per-SKU榜+单品流量趋势+行业畅销榜(P0,饼+榜单+折线)，选品补货。④流量来源结构——5大流量源排行+入口GMV占比(P1,榜单+饼)，看渠道依赖。⑤投放ROI榜——各商品千川消耗+ROI排行(P1,榜单)，预算分配。⑥搜索机会——四档对标+实时热词机会分+引流词榜+待优化商品(P1,柱+榜单+下钻)，抢词优化。⑦商品5A漏斗——单品A1→A4层间转化(P1,漏斗)，单品诊断。⑧达人/直播带货——达人历史榜+Top直播间+抖音号带货榜+自播vs行业对标(P1,榜单+KPI)，找带货人。⑨价格带直方图(P1)+履约/售后健康(P2)。设计原则：操盘手面以「可下钻的明细榜+漏斗诊断」为主，每个榜支持点行下钻到单品/单达人/单词,接异动归因。

## 还差哪些高价值维度(缺口)

相比现状(22端点已接)，按价值排序还差这些高价值维度——老板说「数据不全」主要就是这几块没接：

【第一优先·诊断闭环缺口(P0级)】
1. 转化流失定位 compass.flow_loss_card——漏斗有了但「流量在哪步漏掉、流失率多少」没接，这是漏斗诊断的灵魂,光有漏斗不知道流失在哪等于没诊断。
2. 自家流量来源排行 compass.flow_source_detail_v2 + yuntu.flowentrystructure——只接了竞品流量(flow_data_v2)，自家「GMV从哪个源来」反而没接，是最该补的结构图。
3. 店铺行业排名 compass.shop_rank + 市占率 yuntu.insightbrandoccupancy——老板面「我排第几」的核心卡缺。
4. 服务健康全套 doudian.statistics(好评率/差评数)+compass.shop_negative_problem(负面问题排行)+compass.prof_exp_score(体验分行业对比)——只接了体验分,缺「客户在骂啥」。

【第二优先·缺整个能力维度(P1级)】
5. 投放ROI compass.core_index_v3——全盘唯一「投钱回报」维度完全空白,操盘手做预算分配最痛。
6. 搜索四档对标 compass.overview_data + 实时热词机会分 realtime_word_overview_v2 + 待优化商品 recommend_optimized_product_v2——搜索只接了趋势和词榜,缺「跟行业差多少、该抢哪些冒头词」。
7. 商品5A漏斗 yuntu.getproductoverview5aanalysis + 带货矩阵 sellmatrix——连接人群资产与单品的关键诊断,看单品种草到成交哪层断了。
8. 达人扩展：Top直播间 top_list + 抖音号带货榜 yuntu.bestsellingauthor + 自播对标 getbrandaccountliveoverview——只接了达人历史榜。
9. 今日大盘 doudian.homepage + GTA月度目标 getaudiencegtaprofile——老板面头条的实时今日数+目标达成。

【第三优先·锦上添花(P2级)】
10. 品牌心智(getoverview/listbrandtopkeyword)+NSR口碑(getbrandnsrdetailstats)——长期品牌资产。
11. 行业洞察(marketoverview/trendinsights/branddistribution)+同类竞品清单(good_compete_product_list)。
12. 履约健康(tabcnt/线路准时率)+售后计数(counts)+触点蓄水分布+种草场景流转桑基。

【图表组件缺口(影响呈现,需新建)】
价格带直方图、人群堆叠柱(自家vs行业)、达人榜组件、搜索词榜组件、桑基/流转图——这5个组件不建,对应主题即使数据接了也呈现不出来。现有KPI卡/折线/漏斗/榜单/5A分层/下钻树可复用覆盖约70%主题。

## 附:204 端点分类明细(bi_worthy=high/med)

| 端点 | 平台 | 主题 | 视角 | 能呈现 | 形态 | 价值 | 图表 | 已接 |
|---|---|---|---|---|---|---|---|---|
| compass.prof_exp_score | compass | 服务体验 | boss | 首页体验分摘要——分值 + 行业对比标签（KPI卡呈现店铺体验分） | 单值 | high | KPI卡 |  |
| compass.list | compass | 达人合作带货 | operator | 达人合作历史榜——各达人粉丝数/近期GMV/累计GMV/合作次数 | 榜单 | high | 榜单表 | ★ |
| compass.realtime_word_overview_v2 | compass | 搜索流量 | operator | 行业实时最热词 + 趋势方向 + 机会分（找选品/内容切入的热词） | 榜单 | high | 榜单表 |  |
| compass.overview_data_trend | compass | 搜索流量 | operator | 搜索GMV近7天每日走势曲线 | 时间序列 | high | 折线 | ★ |
| compass.overview_data | compass | 搜索流量 | both | 搜索流量4维行业对标——自家店铺 vs 行业基准/标杆/顶尖三档水平的差距 | 分层 | high | 柱 |  |
| doudian.getoverviewbyversion | doudian | 服务体验 | boss | 店铺体验分总览（抖店镜像版，核心经营健康指标） | 单值 | high | KPI卡 | ★ |
| doudian.statistics | doudian | 服务体验 | boss | 评价管理总览：好评率 / 差评数 / 中差评计数 | 单值 | high | KPI卡 |  |
| doudian.homepage | doudian | 经营大盘 | boss | 抖店首页今日 GMV 大盘 dashboard | 单值 | high | KPI卡 |  |
| yuntu.productstructure | yuntu | 商品per-SKU | operator | 货品结构：各商品GMV占比，看爆款/常规品结构是否健康 | 分布 | high | 饼 | ★ |
| yuntu.getbrandaccountliveoverview | yuntu | 直播 | both | 本品牌直播间表现(GMV/GPM/观看人数/转化率) vs 行业Top对比 | 单值 | high | KPI卡 |  |
| yuntu.insightbrandoccupancy | yuntu | 竞品与行业 | boss | 品牌行业市占率+占比变化+排名(在多少品牌中排第几) | 单值 | high | KPI卡(市占率%+排名+环比) |  |
| yuntu.audienceflowanalysisv2 | yuntu | 人群资产(5A·八大人群) | operator | 5A各层人群流转的本期vs上期同环比(增减率) | 分层 | high | 堆叠柱/瀑布(各层环比变化) | ★ |
| yuntu.get_audience_asset_trend | yuntu | 人群资产(5A·八大人群) | both | 5A各层(A1-A5)资产人数近30天走势 | 时间序列 | high | 多线折线(A1-A5随时间) | ★ |
| yuntu.getaudienceassetstructure | yuntu | 人群资产(5A·八大人群) | operator | 本品牌5A人群结构 vs 行业TOP20品牌均值的对标(各层人数/占比) | 分布 | high | 堆叠柱(自家vs行业基准) | ★ |
| yuntu.getproductoverview5aanalysis | yuntu | 转化漏斗 | operator | 商品 5A 人群漏斗：A1→A4 各层人数及层间转化率（种草到成交哪卡了） | 分层 | high | 漏斗 |  |
| yuntu.flowentrystructure | yuntu | 流量来源 | both | 各流量入口的成交额与流量占比结构（GMV 主要从哪个入口来） | 分布(占比) | high | 饼 |  |
| yuntu.bestsellingproduct | yuntu | 商品per-SKU | operator | 行业畅销商品榜：商品名 + GMV + 占比 + 排名（看行业爆款选品） | 榜单(per实体) | high | 榜单表 | ★ |
| yuntu.bestsellingauthor | yuntu | 达人合作带货 | operator | 抖音号带货销量榜：各达人 GMV 及占比（找谁带货带得动） | 榜单(per实体) | high | 榜单表 |  |
| yuntu.getaudiencegtaprofile | yuntu | 经营大盘 | boss | GTA 生意目标的月度 GMV 同环比趋势（盯目标达成与下滑） | 时间序列 | high | 折线 |  |
| yuntu.audienceflowanalysisv2 | yuntu | 人群资产(5A·八大人群) | both | 5A 各层人群流转规模同环比（上期 vs 本期覆盖人数+变化率） | 分层 | high | 堆叠 | ★ |
| yuntu.get_audience_asset_trend | yuntu | 人群资产(5A·八大人群) | both | 5A 各层（A1-A5）30 天资产人数与占比走势 | 时间序列 | high | 折线 | ★ |
| yuntu.getaudienceassetstructure | yuntu | 人群资产(5A·八大人群) | both | 本品牌 5A 人群结构 vs 行业 TOP20 品牌均值对标（各层人数+占比） | 分层 | high | 堆叠 | ★ |
| compass.prof_exp_score | compass | 服务体验 | boss | 店铺体验分摘要 + 行业对比标签 | 单值 | high | KPI卡 |  |
| compass.list | compass | 达人合作带货 | operator | 合作达人历史明细（粉丝数/近期GMV/累计GMV/合作次数） | 明细表 | high | 榜单表 | ★ |
| compass.overview_data_trend | compass | 搜索流量 | operator | 近7天搜索GMV每天走势 | 时间序列 | high | 折线 | ★ |
| compass.overview_data | compass | 搜索流量 | both | 店铺搜索表现 vs 行业基准/优秀/顶尖四档对标 | 分层 | high | 柱 |  |
| compass.shop_negative_problem | compass | 服务体验 | boss | 店铺各类负面问题按出现次数排行（哪类问题最多） | 榜单 | high | 榜单表 |  |
| compass.prof_exp_score | compass | 服务体验 | boss | 首页体验分摘要 + 行业对比标签 | 单值 | high | KPI卡 |  |
| compass.overview_data_trend | compass | 搜索流量 | both | 搜索GMV近7天每天走势 | 时间序列 | high | 折线 | ★ |
| compass.overview_data | compass | 搜索流量 | both | 搜索维度本店 vs 行业基准/优秀/顶尖四档对标 | 分层 | high | 柱 |  |
| compass.trend_v3 | compass | 商品per-SKU | operator | 单品流量趋势曲线+同行基准对比,看某个品的流量走势是涨还是跌 | 时间序列 | high | 折线 | ★ |
| compass.category_overview_price_band_distribution | compass | 价格与选品 | both | 调味品类目各价格带的GMV占比/销量占比/在售店铺数,看定价该卡哪个价位带 | 分布(占比) | high | 价格带直方图 | ★ |
| compass.flow_loss_card | compass | 转化漏斗 | operator | 店铺流量在各环节的流失量与流失率,定位流量在哪一步漏掉了 | 分层 | high | 漏斗 |  |
| compass.flow_source_detail_v2 | compass | 流量来源 | operator | 店铺5大流量源排行(各源曝光/点击/支付人数),看流量结构靠哪个渠道 | 榜单(per实体) | high | 榜单表 |  |
| compass.flow_source_funnel | compass | 转化漏斗 | both | 店铺曝光-点击-成交全链路漏斗+各环节流量来源构成,找转化卡在哪一层 | 分层 | high | 漏斗 | ★ |
| compass.flow_overview_card | compass | 流量来源 | both | 店铺流量大盘核心指标(曝光人数/点击人数)+环比+同行标杆,看整体流量盘子 | 单值 | high | KPI卡 |  |
| compass.sku | compass | 商品per-SKU | both | 单品按SKU规格拆销量/支付金额/库存,看哪个规格卖得动、哪个要补货 | 明细表 | high | 榜单表 | ★ |
| compass.shop_rank | compass | 竞品与行业 | boss | 店铺7日行业排名第几名+排名涨跌+同行店铺数,看自己在赛道里的位置 | 单值 | high | KPI卡 |  |
| compass.core_trend_v3 | compass | 经营大盘 | boss | 店铺核心指标日趋势曲线+同环比,老板盯今日大盘有没有异动 | 时间序列 | high | 折线 | ★ |
| compass.core_index_v3 | compass | 投放(千川·广告) | operator | 各商品的千川广告消耗与ROI排行,看投钱投在哪个品上回报最高 | 榜单(per实体) | high | 榜单表 |  |
| doudian.doudian_shop_overview | doudian | 经营大盘 | both | 商品/店铺诊断概览（流量超X%同行、转化分位、7天趋势）——但与罗盘 doudian_shop_overview 重复 | 分层 | med | KPI卡 | ★ |
| doudian.getlogisticsdiagnosislinearriveontimeratelist | doudian | 物流履约 | operator | 各物流线路的准时送达率排行（哪条线路爱晚点） | 榜单(per线路) | med | 榜单表 |  |
| compass.core_index | compass | 经营大盘 | boss | 大促周期 vs 日常周期GMV对比（当前额 vs 目标额，看大促同期增幅） | 单值 | med | KPI卡 |  |
| compass.top_list | compass | 达人合作带货 | operator | 达人Top直播间榜——按支付金额排名的直播间清单 | 榜单 | med | 榜单表 |  |
| compass.card_list | compass | 达人合作带货 | operator | 达人同行同层对比——直播/视频/商品卡分别高于X%同行的领先比例 | 分布 | med | 柱 |  |
| compass.shop_video_list | compass | 搜索流量 | operator | 我的视频带来多少搜索（看后搜UV/看后搜率），衡量内容反哺搜索的效果 | 明细表 | med | 榜单表 |  |
| compass.recommend_optimized_product_v2 | compass | 搜索流量 | operator | 哪些商品搜索需优化——按商品列出诊断标签 + 优化建议 | 明细表 | med | 榜单表 |  |
| compass.shop_rank_1 | compass | 搜索流量 | both | 店铺搜索排名第几名 + 头部店铺及其搜索GMV榜 | 榜单 | med | KPI卡 |  |
| compass.weekly_report_summary | compass | 搜索流量 | operator | 上周搜索GMV及周环比（wow_ratio），搜索渠道周度表现一眼看涨跌 | 单值 | med | KPI卡 |  |
| compass.shop_negative_problem | compass | 服务体验 | boss | 店铺负面问题汇总——各类问题的发生次数排行（如物流慢/质量差/客服差各多少条） | 榜单 | med | 榜单表 |  |
| doudian.getdiagnosisconclusion | doudian | 物流履约 | operator | 履约诊断结论：拒签率 / 退货物流回传率 | 单值 | med | KPI卡 |  |
| doudian.getcompassdiagnosis | doudian | 经营大盘 | boss | 店铺等级（综合经营评级单值） | 单值 | med | KPI卡 |  |
| doudian.get_ticket_list | doudian | 服务体验 | boss | 平台罚单按违规原因分类的明细/计数 | 明细表 | med | 榜单表 |  |
| doudian.counts | doudian | 售后退款 | operator | 今天待处理售后单数量 | 单值 | med | KPI卡 |  |
| doudian.tabcnt | doudian | 物流履约 | operator | 今天各订单状态的数量（待发货/待付款/配送中/全部）一组计数卡 | 单值 | med | KPI卡 |  |
| yuntu.industry | yuntu | 搜索流量 | both | 行业整体搜索表现(行业搜索大盘对标) | 时间序列 | med | 折线 |  |
| yuntu.tendency | yuntu | 搜索流量 | operator | 搜索维度的时间趋势(搜索量/搜索GMV走势) | 时间序列 | med | 折线 |  |
| yuntu.rank | yuntu | 搜索流量 | operator | 搜索维度的排行榜(搜索词/品牌/商品搜索排名) | 榜单 | med | 榜单表 |  |
| yuntu.distribution_1 | yuntu | 搜索流量 | operator | 搜索相关的分布拆解(搜索成交按维度的占比分布) | 分布 | med | 饼 |  |
| yuntu.metrics_1 | yuntu | 搜索流量 | operator | 行业搜索维度的核心指标(搜索量/搜索成交等汇总) | 单值 | med | KPI卡 |  |
| yuntu.trendinsights | yuntu | 竞品与行业 | both | 调味品行业趋势洞察(行业热度/品类增长方向走势) | 时间序列 | med | 折线 |  |
| yuntu.customer | yuntu | 竞品与行业 | operator | 行业层面的消费者洞察(行业人群画像/消费偏好分布) | 分布 | med | 分布 |  |
| yuntu.marketoverview | yuntu | 竞品与行业 | boss | 调味品行业大盘概览(行业整体GMV/规模/增速等汇总指标) | 单值 | med | KPI卡 |  |
| yuntu.trendinsights | yuntu | 竞品与行业 | both | 调味品行业趋势洞察（行业增长/热点走势） | 时间序列 | med | 折线 |  |
| yuntu.customer | yuntu | 人群资产(5A·八大人群) | operator | 调味品行业消费者洞察（行业人群画像/消费习惯） | 分布 | med | 分布 |  |
| yuntu.marketoverview | yuntu | 竞品与行业 | boss | 调味品行业大盘概览（市场规模/趋势的总览卡） | 单值 | med | KPI卡 |  |
| yuntu.getaudiencemap_1 | yuntu | 人群资产(5A·八大人群) | operator | 4大群体人群分布(八大人群之子集,占比) | 分布 | med | 饼 |  |
| yuntu.getaudiencegtaecomindustry | yuntu | 竞品与行业 | both | 行业电商对比：本品触点效能vs行业TOP5/中位数基准 | 单值 | med | KPI卡 |  |
| yuntu.getaudiencegtaroadmap | yuntu | 人群资产(5A·八大人群) | operator | 触点效能vs行业对比信号：视频/直播触点曝光与转化是否高于竞品 | 分层 | med | 堆叠 |  |
| yuntu.insightproductstats | yuntu | 竞品与行业 | operator | 细分市场vs全行业SPU成交额排名对比，看自家品在赛道里的位置 | 榜单 | med | 榜单表 |  |
| yuntu.getbrandaccountliveroommetrics | yuntu | 直播 | operator | 单直播间复盘指标（room_metrics整块，需展开看具体场次表现） | 明细表 | med | 榜单表 |  |
| yuntu.sellmatrix | yuntu | 人群资产(5A·八大人群) | operator | 带货矩阵：A1到A5各层覆盖人数，看5A人群资产蓄水结构 | 分层 | med | 漏斗 |  |
| yuntu.branddistribution | yuntu | 竞品与行业 | operator | 品牌分布：行业内各品牌的份额分布 | 分布 | med | 饼 |  |
| yuntu.corebrand | yuntu | 竞品与行业 | both | 行业近30天搜索品牌榜：哪些品牌搜索排名靠前 | 榜单 | med | 榜单表 | ★ |
| yuntu.gethotspotrecommanded | yuntu | 内容(短视频·图文) | operator | 调味品行业热点榜：热度分+标签+趋势，给内容选题做参考 | 榜单 | med | 榜单表 |  |
| yuntu.getbrandnsrdetailstats | yuntu | 服务体验 | boss | 品牌口碑NSR净推荐声量(正面/中性/负面占比) | 分布 | med | 堆叠条/折线(正中负随时间) |  |
| yuntu.listindustrydiscoverkeywordstats | yuntu | 搜索流量 | operator | 行业发现词按lift提升度的排行(机会词挖掘) | 榜单 | med | 横向条形榜(词×lift) |  |
| yuntu.listbrandtopkeyword | yuntu | 竞品与行业 | boss | 品牌相关Top心智词及其趋势(用户怎么记住品牌) | 榜单 | med | 榜单表+迷你趋势(词×trend) |  |
| yuntu.getoverview | yuntu | 竞品与行业 | boss | 品牌心智核心总览(品牌联想量+行业联想排名) | 单值 | med | KPI卡(联想量+排名) |  |
| yuntu.flowsceneanalysisv2 | yuntu | 人群资产(5A·八大人群) | operator | 拉新场景里各云图人群包带来的覆盖人数贡献 | 榜单 | med | 横向条形榜(人群包贡献) |  |
| yuntu.audienceflowsceneanalysisv2 | yuntu | 人群资产(5A·八大人群) | operator | 5A各层间的种草流转(O→A3各场景的迁移人数) | 分层 | med | 桑基/流转图(from→to) |  |
| yuntu.get_audience_asset_trigger_point_distribution | yuntu | 人群资产(5A·八大人群) | operator | A1触点蓄水来源分布(视频vs直播各覆盖多少人) | 分布 | med | 饼/占比条(触点来源) |  |
| yuntu.getaudienceassetbig8trend | yuntu | 人群资产(5A·八大人群) | operator | A2层八大人群(如Z世代)随时间的人数/占比趋势 | 时间序列 | med | 折线(多群体随时间) | ★ |
| yuntu.getaudienceassetbig8profile | yuntu | 人群资产(5A·八大人群) | operator | 结案人群的八大人群兴趣词跨心智分布(哪类八大人群占主导) | 分布 | med | 榜单表(八大人群×兴趣词) | ★ |
| yuntu.getspucontribution | yuntu | 人群资产(5A·八大人群) | operator | 5A 蓄水期成交贡献：蓄水 1 天 vs 15 天的 GMV 与 SPU 成交占比对比（种草是否转化） | 分层 | med | 柱 |  |
| yuntu.getbrandnsrdetailstats | yuntu | 竞品与行业 | boss | 品牌净推荐口碑结构：正面/中性/负面声量占比 | 分布(占比) | med | 堆叠 |  |
| yuntu.listindustrydiscoverkeywordstats | yuntu | 搜索流量 | operator | 行业 lift 高潜关键词排行（哪些词正在冒头值得抢） | 榜单(per实体) | med | 榜单表 |  |
| yuntu.listbrandtopkeyword | yuntu | 人群资产(5A·八大人群) | operator | 品牌心智 Top 关联词及各词的热度趋势（消费者怎么想你） | 榜单(per实体) | med | 榜单表 |  |
| yuntu.getoverview | yuntu | 竞品与行业 | boss | 品牌心智核心总览：心智关联人数 + 在行业里的关联排名 | 单值 | med | KPI卡 |  |
| yuntu.search | yuntu | 人群资产(5A·八大人群) | operator | 已建自定义人群包按覆盖人数排序的榜单（含启用状态） | 榜单 | med | 榜单表 |  |
| yuntu.flowsceneanalysisv2 | yuntu | 人群资产(5A·八大人群) | operator | 拉新场景下各云图人群包对覆盖人数的贡献 | 榜单 | med | 榜单表 |  |
| yuntu.audienceflowsceneanalysisv2 | yuntu | 人群资产(5A·八大人群) | operator | 5A 种草场景流转（O→A3 各场景间人群流动量） | 分层 | med | 下钻树 |  |
| yuntu.get_audience_asset_trigger_point_distribution | yuntu | 人群资产(5A·八大人群) | operator | A1 触点蓄水来源分布（视频 vs 直播各覆盖多少人/占比） | 分布 | med | 饼 |  |
| yuntu.getaudienceassetbig8trend | yuntu | 人群资产(5A·八大人群) | operator | A2 层八大群体（如 Z 世代）随时间的人数与占比趋势 | 时间序列 | med | 折线 | ★ |
| yuntu.getaudienceassetbig8profile | yuntu | 人群资产(5A·八大人群) | operator | 结案受众的八大人群画像与兴趣词跨心智分布 | 分布 | med | 柱 | ★ |
| compass.core_index | compass | 经营大盘 | boss | 大促周期 vs 日常GMV目标完成度对比 | 单值 | med | KPI卡 |  |
| compass.top_list | compass | 达人合作带货 | operator | 达人合作直播间按GMV排行榜 | 榜单 | med | 榜单表 |  |
| compass.card_list | compass | 达人合作带货 | operator | 达人直播/视频/商品卡高于同行的占比对比 | 分布 | med | 柱 |  |
| compass.realtime_word_overview_v2 | compass | 搜索流量 | operator | 行业实时热词 + 趋势方向 + 机会分 | 榜单 | med | 榜单表 |  |
| compass.shop_video_list | compass | 内容(短视频·图文) | operator | 各视频带来的看后搜索人数及看后搜率 | 榜单 | med | 榜单表 |  |
| compass.word_rank | compass | 搜索流量 | operator | 引流词下挂的商品清单（词→商品下钻） | 明细表 | med | 下钻树 | ★ |
| compass.recommend_optimized_product_v2 | compass | 搜索流量 | operator | 哪些商品搜索表现差需要优化（带标签+优化建议） | 明细表 | med | 榜单表 |  |
| compass.shop_rank_1 | compass | 竞品与行业 | boss | 店铺搜索排名第几 + 头部店铺GMV对比 | 榜单 | med | KPI卡 |  |
| compass.weekly_report_summary | compass | 搜索流量 | boss | 上周搜索GMV及周环比 | 单值 | med | KPI卡 |  |
| compass.list | compass | 达人合作带货 | operator | 达人合作历史榜:粉丝数/近期及累计GMV/合作次数 | 榜单 | med | 榜单表 | ★ |
| compass.realtime_word_overview_v2 | compass | 搜索流量 | operator | 行业实时热词 + 趋势方向 + 机会分(选词机会) | 榜单 | med | 榜单表 |  |
| compass.shop_video_list | compass | 内容(短视频·图文) | operator | 各视频带来的看后搜UV及看后搜率 | 榜单 | med | 榜单表 |  |
| compass.recommend_optimized_product_v2 | compass | 搜索流量 | operator | 哪些商品搜索需优化 + 标签 + 优化建议 | 明细表 | med | 榜单表 |  |
| compass.shop_rank_1 | compass | 搜索流量 | both | 本店搜索排名第几 + 头部店铺及其支付金额 | 榜单 | med | 榜单表 |  |
| compass.weekly_report_summary | compass | 搜索流量 | boss | 上周搜索GMV及环比(WoW) | 单值 | med | KPI卡 |  |
| compass.shop_negative_problem | compass | 服务体验 | boss | 店铺负面问题汇总——各类负面问题的出现次数排行(哪类问题最多) | 榜单 | med | 榜单表 |  |
| compass.enter_source_v2 | compass | 流量来源 | operator | 商品卡流量按投放时段/来源拆支付金额,看哪个时段哪个源带货 | 分布(占比) | med | 柱 |  |
| compass.core_data | compass | 转化漏斗 | operator | 商品卡的UV价值(每访客带来的GMV),衡量商品卡流量变现效率 | 单值 | med | KPI卡 |  |
| compass.good_compete_product_list | compass | 竞品与行业 | operator | 某SKU的同类竞品清单(标题/主图/价格带),看对标品都长啥样卖多少钱 | 榜单(per实体) | med | 榜单表 |  |
| compass.flow_data_v2 | compass | 竞品与行业 | operator | 大促榜单上对手爆款的流量结构(各流量源曝光/支付),扒竞品怎么搞流量 | 分布(占比) | med | 堆叠 | ★ |

---

## 全量 16 主题执行路线（2026-06-03 老板拍板"全量"）

多轮工程，按价值分批。每批：探测真实结构 → workflow 写抽取器 → 落库(mvp_daily_metric 全店标量 / 现有维表 / 新维表) → 注册指标 → 前端图表 → 验证。

| 批 | 主题/端点 | 落库去向 | 前端 | 状态 |
|---|---|---|---|---|
| 已完成 | per-SKU商品 + 7维表(价格带/八大人群/达人/搜索词/流量/畅销) | mvp_daily_metric + 7维表 | 仅产品榜可见(复用RankChart) | ✅ 数据层done |
| **第1批** | 投放ROI(core_index_v3)/流失定位(flow_loss_card)/自家5源排行(flow_source_detail_v2)/流量大盘(flow_overview_card)/商品卡UV(core_data)/时段来源(enter_source_v2)/行业排名(shop_rank)/体验分对比(prof_exp_score)/搜索四档对标(overview_data)/好评差评(doudian.statistics)/今日大盘(doudian.homepage) | 多数全店标量→mvp_daily_metric；投放ROI/5源→维表 | KPI卡/折线/榜单复用 | 🔄 已探测,待抽取器 |
| 第2批(前端) | **让已落库的7维表可见** | — | 5新组件:价格带直方图/人群堆叠/达人榜/搜索词榜/桑基 + 挂操盘手面 + 重打包 | ⏳ |
| 第3批 | 商品5A漏斗/搜索热词机会/达人扩展(Top直播间/抖音号带货)/市占率(需参数) | 维表+标量 | 漏斗/榜单复用 | ⏳ |
| 第4批 | P2:品牌心智/NSR口碑/竞品行业/物流履约/售后退款 | 标量+维表 | KPI/榜单复用 | ⏳ |

**关键**：除产品榜外，已落库的 7 维表 + 第1批数据**都要前端图表才看得见**。最快可见跳跃=第2批(前端 surface 已有 7 维表)。
