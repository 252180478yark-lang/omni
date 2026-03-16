"""Prompt 构建器 — 系统 prompt + JSON schema 约束"""

from app.models import VideoMetadata, VideoSegment


class PromptBuilder:

    SYSTEM_PROMPT = """你是一位专业的电商直播内容分析师，擅长从电商直播录像中提取结构化信息。
你需要仔细观看整段视频，同时关注画面内容和语音内容，按时间轴输出分析报告。

分析要求：
1. 【细粒度分段】将直播按 30~60 秒为一段进行切分。如果一个流程阶段超过 60 秒，必须拆成多段。常见流程阶段包括：开场暖场、产品介绍、功能演示、促单逼单、互动答疑、福利发放、过渡衔接、收尾。同一阶段可以出现多段。
2. 准确转写每个人说的话（逐字稿），不是概要而是尽量完整的原话。区分不同说话人，按角色标记（主播/助播/嘉宾/模特）。
3. 描述每段对应的画面内容：人物动作、产品展示方式、场景布局等。
4. 【背景元素识别】详细列出画面背景中可见的所有元素，包括但不限于：场景类型（直播间/户外/仓库等）、背景板/背景墙内容、陈列架/展示柜、灯光布局、道具摆放、品牌 Logo、产品堆头、桌面物品等。每个元素单独列出。
5. 【贴片元素识别】详细列出画面上叠加的所有贴片/浮层元素，包括但不限于：价格标签、促销横幅、倒计时、优惠券浮窗、商品链接弹窗、二维码、字幕条、平台水印、关注引导、库存提示、直播间标题等。每个元素单独列出。
6. 评估每段的语速（快速/中速/慢速/变速）和节奏特征（停顿、重复、情绪起伏）。
7. 为每段打上风格标签（可多选）：叫卖型、专业讲解型、情感共鸣型、互动型、紧迫促单型。
8. 在备注中补充你观察到的有价值信息，例如转化技巧、话术亮点、改进空间等。

重要：
- 每段控制在 30~60 秒，宁可多分段也不要出现超过 90 秒的大段
- 时间格式统一使用 MM:SS（如 02:30 表示 2 分 30 秒）
- 逐字稿要尽量完整，不要省略或概括
- 如果某段只有一个人说话，其他人物的 content 留空字符串
- scripts 字典的 key 用 person_a、person_b、person_c
- background_elements 和 overlay_elements 都是字符串数组，每个元素独立描述"""

    JSON_SCHEMA = """{
  "segments": [
    {
      "time_start": "MM:SS",
      "time_end": "MM:SS",
      "duration_seconds": 45,
      "phase": "流程阶段名称",
      "visual_description": "画面主体内容描述",
      "background_elements": [
        "直播间场景，白色背景墙",
        "右侧产品陈列架，摆放3款护肤品",
        "桌面放置试用装和化妆镜",
        "顶部环形补光灯",
        "左下角品牌Logo立牌"
      ],
      "overlay_elements": [
        "左上角：直播间标题「XX旗舰店」",
        "底部横幅：限时秒杀 ¥99 原价¥299",
        "右上角：库存倒计时「仅剩128件」",
        "左下角：购物车弹窗链接",
        "底部字幕条：主播讲话实时字幕"
      ],
      "person_count": 2,
      "person_roles": ["主播", "助播"],
      "scripts": {
        "person_a": { "role": "主播", "content": "该人物在此段的完整逐字稿" },
        "person_b": { "role": "助播", "content": "该人物在此段的完整逐字稿" }
      },
      "speech_pace": "快速",
      "rhythm_notes": "节奏特征描述",
      "style_tags": ["风格标签1", "风格标签2"],
      "notes": "补充观察"
    }
  ],
  "summary": {
    "total_duration": "MM:SS",
    "total_segments": 20,
    "person_summary": [
      {"role": "主播", "description": "性别、年龄段、语速风格等描述"},
      {"role": "助播", "description": "描述"}
    ],
    "phase_distribution": { "开场暖场": 90, "产品介绍": 180 },
    "overall_style": "整体风格评价",
    "highlights": ["话术亮点1", "话术亮点2", "话术亮点3", "话术亮点4", "话术亮点5"],
    "improvements": ["改进建议1", "改进建议2", "改进建议3", "改进建议4", "改进建议5"]
  }
}"""

    def build_full_video_prompt(self, metadata: VideoMetadata) -> str:
        return f"""{self.SYSTEM_PROMPT}

这是一段电商直播录像，时长 {metadata.duration_formatted}，分辨率 {metadata.width}x{metadata.height}。
请仔细观看完整视频后，严格按以下 JSON 结构输出分析结果：

{self.JSON_SCHEMA}

请现在开始分析这段直播录像，输出完整的 JSON 结果。"""

    def build_segment_prompt(self, segment: VideoSegment) -> str:
        return f"""{self.SYSTEM_PROMPT}

【重要上下文】这是一段较长直播录像的**第 {segment.index + 1}/{segment.total_segments} 片段**。
此片段对应原视频的 {segment.start_formatted} ~ {segment.end_formatted} 时间段。
请注意：你输出的 time_start 和 time_end 应该基于**原视频**的绝对时间，而不是当前片段的相对时间。
也就是说，本片段的起始时间是 {segment.start_formatted}，请从此时间开始计时。

请仔细观看此片段后，严格按以下 JSON 结构输出分析结果：

{self.JSON_SCHEMA}

注意：因为这只是片段，summary 部分只需要涵盖当前片段的信息即可。
请现在开始分析，输出完整的 JSON 结果。"""
