### 第 0 部分：人群画像扩展

咱这次要圈的是【家庭伦理团】（都市情感族），这帮人的画像大概是这样：

- **生活方式**：平时闲下来就爱刷抖音，特别爱看家庭伦理、年代、婆媳、代际类的短剧打发时间 `[KB]`。属于中线稳健活力派，日常负责全家的一日三餐，很看重代际关系和家庭和睦 `[KB]`。
- **消费习惯**：买东西务实，平时常买厨房用具、保健食品和传统滋补品 `[KB]`。对老字号有天然的好感和信任，愿意为家人的健康花钱买好东西 `[matrix 1.1.2 + 行业推理]`。不过 KB 里没给具体的消费力档位和人口属性数据，**信息不足，建议老板在后台补看一下这波人的客单价接受度**。
- **痛点**：年纪上来了，有控糖养生的刚需，怕吃得太咸或者糖分超标影响健康 `[matrix 1.1.1 + KB]`。平时做家常菜、红烧炖煮时，用普通酱油容易死咸、没酱香 `[matrix 1.2.2 + 1.2.3]`。
- **触发场景**：刷到婆媳短剧里一家人吃饭的场景，或者看到老字号讲传统酿造工艺的视频，联想到该给家里换瓶配料干净、提香不齁咸的好酱油了 `[KB + matrix 1.3]`。

### 第 1 部分：4 维参数判定 + 双线匹配 + 综合选定

> ## 4 维参数判定
> - 投放阶段：O→A1（固定，video_soft_ad 默认）
> - 目标时长：45s（推断：节日情感向叙事需要铺垫空间）
> - 内容定位：节日（老板指定：母亲节）
> - SKU 定位：中高端线（推断：售价 76 元）
> - 制作预算：中-高（推断：节日大促节点）

> ## 1.1 人群 → 方法论候选
> 按 2.1 第一层路由表，结合 audience.kb_chunk_text 的偏好叙事线索：
> - 候选 M4：适合节日大事件，能提供家庭伦理团爱看的戏剧冲突和人物行动。
> - 候选 M5：适合女性向情感，能提供家庭伦理团吃的那套共情递进和情绪升华。
> - 候选 M4+M5 组合：节日大促女性向的标配，M4 做骨架，M5 填情感。

> ## 1.2 人群 → 母题候选
> 1. 发现她做菜越来越咸的那天 [来源：M3.5 家庭伦理团母题库]
> 2. 婆媳在厨房的沉默和解 [来源：M3.5 家庭伦理团母题库]
> 3. 照着她的菜谱却做不出那个味 [来源：自由穷举/matrix 1.2.2]
> 4. 远嫁女儿复刻的年夜饭 [来源：M3.5 家庭伦理团母题库]
> 5. 她说"我不饿你们吃"的谎言 [来源：自由穷举/家庭伦理剧桥段]

> ## 1.3 综合选定
> **选定方法论**：M4 + M5 组合（Hero's Journey + Empathy Marketing）
> **选定母题**：发现她做菜越来越咸的那天
> 
> **综合判定理由**：
> 1. **人群偏好叙事**：家庭伦理团看重代际关系，吃情感共鸣，M4+M5 能把母女间的情感变化讲透。
> 2. **人群偏好母题方向**：母亲节节点，"发现妈妈老了"这个母题杀伤力极强，能瞬间抓住30-50岁女性。
> 3. **4 维参数收窄**：母亲节（节日）+ 45s 时长 + 中高端 SKU，纯日常流压不住阵，必须上带情感弧线的 M4+M5。
> 4. **方法论 × 母题 的契合度**：M4 的"跨越门槛"正好装下女儿接手厨房的行动，M5 的"认可"层正好化解"妈妈做菜难吃"的尴尬（不是她的错，是老了）。
> 5. **对比其他候选**：比纯 M3 更有节日仪式感，比纯 M6 成本更可控且更接地气。

### 第 2 部分：共鸣点穷举

> **共鸣点穷举（8 条按"这就是我"浓度倒序，全部紧扣选定母题）**
> 1. 发现她做菜越来越咸的那天 [来源：行业推理：老人味觉退化]（紧扣母题：发现妈妈老了）
> 2. 饭桌上没人讲话的那秒 [来源：人群画像生活方式]（紧扣母题：菜太咸了没人好意思说）
> 3. "中年儿媳"的第一个母亲节 [来源：人群画像婆媳偏好]（紧扣母题：两代妈妈的交接）
> 4. 凌晨 1 点在厨房备菜的二胎宝妈 [来源：人群画像顾家特征]（紧扣母题：理解妈妈当年的辛苦）
> 5. 照着她的菜谱却做不出那个味 [来源：matrix 1.2.2 炒菜酱香]（紧扣母题：妈妈味道的传承）
> 6. 35岁才懂她当年为什么爱买老牌子 [来源：matrix 1.1.2 33年老厂]（紧扣母题：消费观的代际传承）
> 7. 看着她满头白发还在厨房忙活 [来源：人群画像代际偏好]（紧扣母题：心疼妈妈）
> 8. "妈昨晚又给打电话" [来源：人群画像生活方式]（紧扣母题：远嫁女儿的日常愧疚）

### 第 3 部分：脚本元信息表

| 字段 | 值 |
|---|---|
| 调用方法论 | M4 + M5 组合 |
| 投放阶段 | O→A1 |
| 目标人群 | 家庭伦理团 |
| SKU | 和田宽有机本酿造特级酱油 |
| 母题 | 发现她做菜越来越咸的那天 |
| 总时长 | 45s |
| 截图传播点 | 原来最好的礼物，是让她尝到年轻时的味道。 |
| 评论召唤点 | 你是什么时候发现妈妈老了的？ |
| 品牌出现次数 | 1（仅片尾署名） |
| 产品在场次数 | 1 |
| 传播动机（具体的人）| 母亲 |

### 第 3.5 部分：角色清单

#### 角色 daughter · 女儿
- **年龄**：35-40 岁
- **性别**：女
- **外貌关键词**：mid-30s, shoulder-length neat hair, slim build, gentle tired face, warm complexion, simple beige knit sweater, soft aura
- **气质 / 神韵**：A working mother who finally understands her own mother's silent sacrifices.
- **人群锚点**：来自第 0 部分人群画像"30-50 岁夹心层女性，顾家养生兼顾者"。

#### 角色 mother · 母亲
- **年龄**：60-65 岁
- **性别**：女
- **外貌关键词**：mid-60s, low gray bun, slightly hunched posture, gentle wrinkled face, traditional floral cotton blouse, weathered hands
- **气质 / 神韵**：A retired mother whose love manifests through cooking but is now quietly defeated by aging taste buds.
- **人群锚点**：来自第 0 部分人群画像"关注代际关系，负责全家三餐的长辈"。

### 第 4 部分：分镜脚本

#### 节点 1 · Ordinary World 现状（0-6s）
- **画面**：饭桌前，女儿夹了一块红烧肉放进嘴里，眉头微不可察地皱了一下。对面妈妈正期待地看着她。
- **台词/字幕**：【画外音独白】这半年来，我妈做菜越来越咸。（首屏字幕只打：这半年来，）
- **镜头**：近景，女儿面部特写，背景里的妈妈虚化。
- **声音**：环境音（碗筷轻碰声），无 BGM。
- **节点内核**：M5 Recognition 层，用"妈妈做菜变咸"这个真实痛点建立共鸣。
- **变化点**：从平静吃饭到皱眉的微表情变化。
- **本段角色**：[daughter, mother]
- **产品出场**：false（纯人物情绪铺垫，不出现产品）
- **image_prompt**：
  A cinematic close-up photograph of character_sheet[daughter] lifting a piece of braised pork to her mouth at a modest family dining table, her brow subtly furrowing in quiet realization. Across from her, character_sheet[mother] sits in soft out-of-focus foreground, watching with subtle anticipation. Soft warm tungsten light from a single overhead pendant lamp ~3000K casts gentle shadows. Composition follows rule of thirds with the daughter occupying the left third. Shot on a 50mm lens at f/2.0 for shallow depth of field. Slightly desaturated warm color palette dominated by amber and umber tones with gentle contrast. Mood is quietly contemplative. 9:16 vertical aspect, photo-realistic documentary style.

#### 节点 2 · Call to Adventure 召唤（6-12s）
- **画面**：女儿站在厨房门口，看着妈妈略微佝偻的背影在灶台前忙碌。
- **台词/字幕**：【画外音独白】后来才懂，她不是口味重了，是味觉退化了。
- **镜头**：过肩镜头，从女儿视角看妈妈的背影。
- **声音**：轻柔的钢琴 BGM 起，抽油烟机低沉的嗡嗡声。
- **节点内核**：M5 Validation 层，告诉观众"这不是妈妈的错"，化解抱怨。
- **变化点**：视角从饭桌转换到厨房，情绪从不解变成心疼。
- **本段角色**：[daughter, mother]
- **产品出场**：false（视线焦点在妈妈背影上）
- **image_prompt**：
  A cinematic over-the-shoulder photograph from the perspective of character_sheet[daughter], looking into a dimly lit kitchen where character_sheet[mother] stands at the stove, her back slightly hunched. Soft warm tungsten light ~3000K illuminates the mother's floral blouse, while the daughter's shoulder in the foreground remains in shadow. Shot on a 50mm lens at f/2.0, shallow depth of field focusing on the mother. Slightly desaturated warm color palette dominated by amber and umber tones. Mood is tender and slightly melancholic. 9:16 vertical aspect, photo-realistic documentary style.

#### 节点 3 · Crossing the Threshold 行动（12-22s）
- **画面**：母亲节这天，女儿系上围裙，把妈妈按在餐桌旁坐下。女儿转身切菜、倒酱油调汁，动作麻利。案板旁放着和田宽酱油。
- **台词/字幕**：【画外音独白】今年的饭，换我来做。不用放那么多盐，靠好酱油的底味也能提鲜。
- **镜头**：中景切近景，女儿做饭的动作连贯，酱油瓶自然入画不特写。
- **声音**：切菜的笃笃声，热油下锅的滋啦声。
- **节点内核**：M4 行动层，主角开始改变现状；产品作为提鲜道具自然在场。
- **变化点**：女儿取代妈妈成为厨房的主角，节奏变快。
- **本段角色**：[daughter, mother]
- **产品出场**：true（产品作为厨房真实调料自然摆放，不给特写）
- **image_prompt**：
  A cinematic medium close-up photograph of character_sheet[daughter] wearing an apron, actively chopping vegetables at a kitchen counter. A glass bottle of dark soy sauce sits naturally in the background among other ingredients, slightly out of focus. Soft warm tungsten light ~3000K highlights her focused expression and the fresh vegetables. Shot on a 50mm lens at f/2.0. Slightly desaturated warm color palette dominated by amber and umber tones. Mood is active and caring. 9:16 vertical aspect, photo-realistic documentary style.

#### 节点 4 · Transformation 蜕变（22-32s）
- **画面**：饭桌上，妈妈吃了一口女儿做的菜，眼睛亮了一下，笑着点点头。女儿在对面托着腮看着她笑。
- **台词/字幕**：【画外音独白】看她吃得开心，突然觉得，这厨房我早该接手了。
- **镜头**：中景双人镜头，两人互动自然温馨。
- **声音**：BGM 走向温暖明亮的高潮。
- **节点内核**：M5 Aspiration 层，行动得到正向反馈，情绪升华。
- **变化点**：从厨房的忙碌转为餐桌上的轻松愉悦。
- **本段角色**：[daughter, mother]
- **产品出场**：false（回归人物情感互动）
- **image_prompt**：
  A cinematic medium shot photograph of character_sheet[mother] and character_sheet[daughter] sitting across from each other at the dining table. The mother is smiling warmly after tasting the food, her eyes bright. The daughter rests her chin on her hand, looking at her mother with deep affection. Soft warm tungsten light ~3000K bathes the scene in a cozy glow. Shot on a 50mm lens at f/2.0. Slightly desaturated warm color palette dominated by amber and umber tones. Mood is heartwarming and joyful. 9:16 vertical aspect, photo-realistic documentary style.

#### 节点 5 · Release 释放（32-40s）
- **画面**：画面定格在妈妈低头吃饭时满足的笑脸上。
- **台词/字幕**：【屏幕字幕】原来最好的礼物，是让她尝到年轻时的味道。
- **镜头**：近景定格，留白给字幕。
- **声音**：BGM 渐弱，留有余音。
- **节点内核**：截图传播点，给出核心金句，触发用户转发给妈妈。
- **变化点**：动态画面转为静态定格，情绪达到顶峰。
- **本段角色**：[mother]
- **产品出场**：false（纯情绪定格）
- **image_prompt**：
  A cinematic close-up photograph of character_sheet[mother] looking down at her meal with a deeply satisfied, gentle smile. Soft warm tungsten light ~3000K highlights the texture of her weathered skin and silver hair. Generous negative space at the bottom for text overlay. Shot on a 50mm lens at f/2.0. Slightly desaturated warm color palette dominated by amber and umber tones. Mood is profoundly peaceful and nostalgic. 9:16 vertical aspect, photo-realistic documentary style.

#### 节点 6 · Soft Sign 署名（40-45s）
- **画面**：纯黑背景，白字浮现。
- **台词/字幕**：【屏幕字幕】和田宽 · 出品。祝妈妈们，节日快乐。
- **镜头**：静帧。
- **声音**：BGM 完全收尾。
- **节点内核**：极简品牌落款，不破坏前面的情绪。
- **变化点**：从生活场景切入纯净的品牌空间。
- **本段角色**：[]
- **产品出场**：false（只出文字水印，不出产品图）
- **image_prompt**：
  A minimalist cinematic frame, pure solid black background with soft grain texture. No subjects, no objects. Mood is quiet and respectful. 9:16 vertical aspect, photo-realistic documentary style.

### 第 5 部分：3 个开头钩子变体

1. **身份+处境钩子**
   - 台词：35岁以后，越来越怕吃我妈做的饭。
   - 画面 hint：女儿看着满桌子菜，面露难色。
   - 适合理由：用反常理的陈述制造悬念，精准击中中年女儿对母亲衰老的隐秘痛点。
   - 共鸣强度：9

2. **瞬间钩子**
   - 台词：饭桌上没人讲话的那秒，是因为菜太咸了。
   - 画面 hint：一家三口吃饭，同时停下筷子，面面相觑。
   - 适合理由：极具生活画面感，把"老人做菜变咸"这个普遍现象具象化。
   - 共鸣强度：8

3. **关系钩子**
   - 台词：中年儿媳的必修课，是学会给婆婆做顿饭。
   - 画面 hint：儿媳在厨房手忙脚乱，婆婆在客厅探头看。
   - 适合理由：切中家庭伦理团最爱看的婆媳关系，把母题平移到婆媳互动上。
   - 共鸣强度：7

### 第 6 部分：双层反作弊

#### 6.A 用户视角自问
1. **我刷到这个视频第 0-5 秒，会划走吗？**
   不会。开头说"我妈做菜越来越咸"，这事儿太真实了，我家老人这两年做菜也是猛放盐，我想看看后面怎么说。
2. **我看到中段，会不会觉得无聊？**
   不会。女儿把妈妈推出厨房自己上手做饭，动作有节奏感，而且我想看看她做出来的菜妈妈吃完什么反应。
3. **视频结束我会不会去评论区？**
   会。我想在评论区吐槽一下我妈现在炒菜有多咸，顺便看看别人家的老人是不是也这样。
4. **我会不会转发？**
   会。想转发给我妈，或者发给几个好闺蜜，感叹一下父母真的老了，以后得多回去给他们做做饭。

#### 6.B 选定模块反作弊三问（M5）
1. **把品牌去掉，这条是不是有价值的女性向/共情向公益内容？**
   是。它讲述了发现母亲衰老的瞬间，以及女儿的反哺，完全可以作为一条母亲节的独立情感短片。
2. **Validation 节是"这不是你的错"还是"你应该更努力"？**
   是"这不是你的错"。"她不是口味重了，是味觉退化了"这句话直接化解了对母亲做菜难吃的抱怨，给出了生理上的合理性。
3. **Aspiration 是温和鼓励还是销售 CTA？**
   是温和鼓励。"今年的饭，换我来做"，没有任何推销意味，只是鼓励大家多给父母做顿饭。

### 第 7 部分：制作指引

- **拍摄难度**：2 星（纯室内家庭场景，机位固定）
- **后期复杂度**：1 星（顺剪，调色偏暖调生活流即可）
- **是否需要演员**：是（需要一对有母女感的演员，微表情要自然）
- **关键道具清单**：和田宽酱油（撕掉防伪贴等杂乱标签）、家常饭菜（红烧肉）、围裙
- **拍摄场景需求**：有生活气息的普通家庭厨房和餐厅，不要太豪华，要有烟火气。
- **预估制作成本量级**：中（5k-30k，主要花在演员和灯光上）

### 第 8 部分：metrics_json

```json
{
  "selected_framework": "empathy",
  "selected_module": "M5",
  "module_combo": "M4+M5",
  "deploy_stage": "O_A1",
  "duration_seconds": 45,
  "dialog_total_words": 62,
  "dialog_words_per_second": 1.37,
  "scene_change_max_gap_seconds": 4,
  "first_subtitle_chars": 5,
  "first_3s_mentions_product": false,
  "brand_first_appearance_second": 40,
  "brand_total_mention_count": 1,
  "selling_point_dialog_count": 0,
  "brand_signature_format": "content_credit",
  "identity_or_setting_hook_present": true,
  "screenshot_share_point_present": true,
  "comment_summon_point_present": true,
  "ending_open": true,
  "hardad_words_present": false,
  "transmission_target": "母亲",
  "pixar_six_sentence_count": 0,
  "cer_twist_present": false,
  "cer_emotion_release_type": "none",
  "slice_setting_specificity_high": false,
  "slice_quality_moment_close_up_count": 0,
  "hero_protagonist_is_ordinary": false,
  "empathy_validation_no_blame": true,
  "cultural_tension_real": false,
  "aspirational_middle_class_reachable": false,
  "doc_real_subject": false,
  "doc_real_interview": false,
  "character_sheet_count": 2,
  "scenes_with_image_prompt_count": 6,
  "scenes_total_count": 6,
  "image_prompt_avg_chars": 138,
  "scene_product_appearance": [false, false, true, false, false, false]
}
```
