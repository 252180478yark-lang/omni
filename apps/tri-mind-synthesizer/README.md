# Tri-Mind Synthesizer

多模型辩论工具 - 让多个 LLM 针对同一问题进行并发对比、交叉质疑与综合裁决。

## 功能特性

- **多模型并发对比**: 同时调用 OpenAI、Anthropic、Google 等多个 LLM
- **多轮辩论**: 支持 1-5 轮辩论，模型间互相"找茬"
- **流式输出**: 实时展示各模型的回答
- **智能压缩**: Token 预算管理，自动压缩历史上下文
- **最终裁决**: 由指定模型汇总所有观点，输出结构化结论
- **快捷键支持**: Ctrl+Enter 发送，Esc 停止，Ctrl+N 新建会话
- **Markdown 导出**: 完整辩论过程导出为 Markdown 文件
- **安全存储**: API Key 使用系统凭据管理器加密存储

## 技术栈

- **桌面框架**: Electron
- **前端**: React 19 + TypeScript + Vite
- **UI**: Shadcn UI + Tailwind CSS
- **状态管理**: Zustand
- **数据库**: better-sqlite3
- **密钥存储**: keytar

## 快速开始

### 安装依赖

```bash
npm install
```

### 开发模式

```bash
npm run electron:dev
```

### 构建应用

```bash
npm run electron:build
```

## 快捷键

| 快捷键 | 功能 |
|--------|------|
| Ctrl+Enter | 发送消息 |
| Esc | 停止生成 |
| Ctrl+N | 新建会话 |
| Ctrl+, | 打开设置 |
| Ctrl+Shift+E | 导出辩论 |

## 支持的模型

- **OpenAI**: GPT-4o, GPT-4 Turbo, GPT-4o Mini
- **Anthropic**: Claude 3.5 Sonnet, Claude 3 Opus, Claude 3 Haiku
- **Google**: Gemini 1.5 Pro, Gemini 1.5 Flash
- **Ollama**: 本地部署的任意模型

## 项目结构

```
tri-mind-synthesizer/
├── electron/           # Electron 主进程
│   ├── main.ts         # 入口文件
│   ├── preload.ts      # 预加载脚本
│   ├── menu.ts         # 应用菜单
│   ├── ipc/            # IPC 处理器
│   └── services/       # 后端服务
├── src/                # React 渲染进程
│   ├── components/     # UI 组件
│   ├── hooks/          # React Hooks
│   ├── stores/         # Zustand 状态
│   └── lib/            # 工具函数和类型
├── package.json
└── vite.config.ts
```

## 开发路线图

- [x] v1.0 (MVP): 多模型并发对比 + 多轮辩论 + Markdown 导出
- [ ] v1.1: 上帝视角干预 + 文件投喂 + 代码 Diff
- [ ] v1.2: 分支与回溯 + 会话模板
- [ ] v2.0: 插件系统 + 团队协作

## License

MIT
