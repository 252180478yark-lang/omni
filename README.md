# Omni / Omni-Vibe OS

> **混合架构智能系统** — Omni-Vibe OS 控制台 + Tri-Mind Synthesizer 多模型辩论工具  
> 一个基于混合架构（本地 RTX + 云端 API）的自进化全栈商业与认知操作系统。

![Status](https://img.shields.io/badge/Status-Active_Development-green)
![Frontend](https://img.shields.io/badge/Frontend-Next.js_14-black)
![AI](https://img.shields.io/badge/AI-Tri--Mind_%7C_Multi--Model-purple)

## 简介

**Omni** 是 Omni-Vibe OS 的统一实现，包含：

- **Omni-Vibe OS 控制台**：Next.js 14 前端，统一入口
- **Tri-Mind Synthesizer**：多模型辩论工具（OpenAI / Anthropic / Gemini / Ollama）
- **未来扩展**：FastAPI 后端、LangGraph、GraphRAG、本地推理等

核心理念：**思考-执行-进化** 闭环，混合本地算力与云端 API。

## 项目结构

```
omni/
├── frontend/           # Next.js 14 应用（控制台 + Tri-Mind）
│   └── src/
│       ├── app/        # 页面与 API 路由
│       ├── components/ # UI 组件
│       └── server/     # 服务端逻辑（辩论控制器、LLM 适配器）
├── backend/            # [FastAPI] 核心业务逻辑（规划中）
├── apps/               # 子应用（如原 Tri-Mind Electron 版，已弃用）
├── 项目拆解/           # 项目拆解文档
├── docker-compose.yml  # 本地基础设施
└── package.json
```

## 快速开始

```bash
# 安装依赖
cd frontend && npm install

# 启动开发服务器
npm run dev
```

访问 **http://localhost:3000**

- 首页：Omni 控制台
- `/tri-mind`：多模型辩论（首页点击入口或直接访问）

## 构建

```bash
npm run build
npm run start   # 生产模式运行
```

## 技术栈

- Next.js 14, React 18, Tailwind CSS, shadcn/ui
- Tri-Mind：多模型辩论（OpenAI / Anthropic / Gemini / Ollama）
- 规划中：FastAPI、LangGraph、GraphRAG、ComfyUI、Ollama

## License

MIT
