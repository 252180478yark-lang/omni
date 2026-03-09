# Omni

混合架构智能系统，集成 Omni-Vibe OS 控制台与 Tri-Mind Synthesizer 多模型辩论工具。

## 项目结构

```
omni/
├── frontend/                    # Next.js 14 控制台
│   └── src/app/                 # App Router
├── apps/
│   └── tri-mind-synthesizer/    # Electron 多模型辩论桌面应用
└── package.json                 # 根脚本
```

## 快速开始

### 前端控制台 (Next.js)

```bash
npm run dev
# 或
cd frontend && npm run dev
```

访问 http://localhost:3000

### Tri-Mind Synthesizer (Electron)

```bash
npm run dev:tri-mind
# 或
cd apps/tri-mind-synthesizer && npm run electron:dev
```

多模型辩论工具 - 让多个 LLM 针对同一问题进行并发对比、交叉质疑与综合裁决。

## 技术栈

- **Frontend**: Next.js 14, React 18, Tailwind CSS, shadcn/ui
- **Tri-Mind**: Electron 33, React 19, Vite 6, Zustand, Tailwind CSS

## 构建

```bash
# 构建前端
npm run build

# 构建 Tri-Mind 桌面应用
npm run build:tri-mind
```

## License

MIT
