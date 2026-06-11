# 出片模型档案 · veo（Google Veo 3.x）

> ⚠️ 初始档案，待实测校准。

- 单次生成时长：~8s/块（75s 视频 ≈ 9-10 块）
- 写法：长叙事散文体友好——人物/场景/镜头运动织进连续描述效果最好；支持镜头术语（dolly/pan/close-up）
- 台词/音频：**支持**——对白写 `Character says: "..."`（带引号），环境音/音效可直接描述（sizzling sounds, door creaks）
- 负向词：原生支持弱，段尾 Negative 行保留但别依赖；重要排除项改写成正向描述（"clean natural skin" 而不是只写 "no plastic skin"）
- 真人感锚保留：handheld iPhone 风格描述 Veo 响应良好
