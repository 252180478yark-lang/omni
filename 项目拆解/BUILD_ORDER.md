# 构建顺序图 / Build Order

## 依赖关系图 / Dependency Graph

```mermaid
graph TD
    subgraph "Phase 1: 基础设施 (Day 1)"
        SP1["🏗️ SP#1: infra-core<br/>PostgreSQL + Redis + Nginx<br/>⏱ 1h"]
    end

    subgraph "Phase 2: 核心框架 (Day 1-2)"
        SP2["🚪 SP#2: backend-gateway<br/>FastAPI + Auth + Celery<br/>⏱ 2-3h"]
    end

    subgraph "Phase 3: AI 能力层 (Day 2-3)"
        SP3["🤖 SP#3: ai-provider-hub<br/>Gemini/OpenAI/Ollama<br/>⏱ 2h"]
        SP4["📚 SP#4: knowledge-engine<br/>GraphRAG + pgvector<br/>⏱ 2-3h"]
    end

    subgraph "Phase 4: 编排层 (Day 3-4)"
        SP5["🧠 SP#5: langgraph-orchestrator<br/>Plan→Execute→Review<br/>⏱ 2-3h"]
    end

    subgraph "Phase 5: 业务模块 (Day 4-7, 可并行)"
        SP6["🎨 SP#6: content-factory<br/>ComfyUI + FFmpeg<br/>⏱ 3h"]
        SP7["📊 SP#7: market-intelligence<br/>DrissionPage 爬虫<br/>⏱ 2-3h"]
        SP8["🤖 SP#8: ops-assistant<br/>RPA + Wechaty<br/>⏱ 2-3h"]
        SP9["🧠 SP#9: second-brain<br/>OCR + Whisper + PDF<br/>⏱ 2-3h"]
    end

    subgraph "Phase 6: 进化引擎 (Day 7-8)"
        SP10["🔄 SP#10: evolution-engine<br/>LLaMA-Factory + LoRA<br/>⏱ 2-3h"]
    end

    subgraph "Phase 7: 前端集成 (Day 8-10)"
        SP11["🖥️ SP#11: frontend-dashboard<br/>Next.js + Shadcn UI<br/>⏱ 3h"]
    end

    SP1 --> SP2
    SP2 --> SP3
    SP2 --> SP4
    SP3 --> SP5
    SP4 --> SP5
    SP2 --> SP6
    SP3 --> SP6
    SP2 --> SP7
    SP4 --> SP7
    SP2 --> SP8
    SP3 --> SP8
    SP2 --> SP9
    SP4 --> SP9
    SP2 --> SP10
    SP3 --> SP10
    SP2 --> SP11

    style SP1 fill:#bbdefb,stroke:#1565c0,color:#000
    style SP2 fill:#bbdefb,stroke:#1565c0,color:#000
    style SP3 fill:#ffe0b2,stroke:#e65100,color:#000
    style SP4 fill:#ffe0b2,stroke:#e65100,color:#000
    style SP5 fill:#f8bbd0,stroke:#c62828,color:#000
    style SP6 fill:#c8e6c9,stroke:#2e7d32,color:#000
    style SP7 fill:#c8e6c9,stroke:#2e7d32,color:#000
    style SP8 fill:#c8e6c9,stroke:#2e7d32,color:#000
    style SP9 fill:#c8e6c9,stroke:#2e7d32,color:#000
    style SP10 fill:#e1bee7,stroke:#6a1b9a,color:#000
    style SP11 fill:#fff9c4,stroke:#f57f17,color:#000
```

## 推荐时间线 / Recommended Timeline

| 天数 | Phase | 子项目 | 估计时间 | 里程碑 |
|------|-------|--------|---------|--------|
| Day 1 | Phase 1-2 | SP#1 + SP#2 | 3-4h | ✅ 基础设施就绪，API 网关可用 |
| Day 2 | Phase 3 | SP#3 + SP#4 | 4-6h | ✅ AI 调用可用，知识检索可用 |
| Day 3-4 | Phase 4 | SP#5 | 2-3h | ✅ 思考环闭环完成 |
| Day 4-5 | Phase 5a | SP#6 + SP#7 | 5-6h | ✅ 内容生成 + 情报爬取 |
| Day 5-6 | Phase 5b | SP#8 + SP#9 | 4-6h | ✅ 运营自动化 + 知识入库 |
| Day 7 | Phase 6 | SP#10 | 2-3h | ✅ 进化引擎就绪 |
| Day 8-10 | Phase 7 | SP#11 | 3h | ✅ 前端仪表盘上线 |

**总计约 25-35 个 Vibe Coding 小时，建议 10 个工作日内完成 MVP。**

## 关键里程碑 / Key Milestones

1. **M1**: `docker compose up postgres redis` 正常运行
2. **M2**: `curl /api/v1/auth/register` 注册用户成功
3. **M3**: `curl /api/v1/ai/chat` AI 对话正常（至少一个 Provider）
4. **M4**: `curl /api/v1/knowledge/query` 知识检索返回结果
5. **M5**: `curl /api/v1/orchestrate/run` 端到端任务执行完成
6. **M6**: 各业务模块 API 独立可用
7. **M7**: `http://localhost:3000` 前端正常访问
8. **M8**: `docker compose up` 全部服务一键启动
