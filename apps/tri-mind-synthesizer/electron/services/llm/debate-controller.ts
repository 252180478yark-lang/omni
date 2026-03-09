import { BrowserWindow } from 'electron'
import { v4 as uuidv4 } from 'uuid'
import { 
  DebateParams, 
  ModelConfig, 
  RoundHistory, 
  StreamChunk,
  DebateEvent,
  TokenUsage,
  ChatNode
} from '../../../src/lib/types'
import { adapterManager } from './adapters'
import { promptFactory } from './prompt-factory'
import { tokenBudgetManager } from './token-budget'
import { getApiKey } from '../credential.service'
import { addNode, updateSession } from '../db.service'

/**
 * 辩论控制器
 * 
 * 负责：
 * 1. 并发调用多个模型
 * 2. 管理 AbortController
 * 3. 协调多轮辩论流程
 * 4. 向渲染进程发送流式数据
 */
export class DebateController {
  private abortControllers: Map<string, AbortController> = new Map()
  private mainWindow: BrowserWindow | null = null

  /**
   * 设置主窗口引用
   */
  setMainWindow(window: BrowserWindow) {
    this.mainWindow = window
  }

  /**
   * 运行辩论
   */
  async runDebate(params: DebateParams): Promise<void> {
    const { sessionId, query, models, rounds, files, intervention, apiKeys, reportDetailLevel } = params
    const runtimeApiKeys = apiKeys || {}
    
    // 创建 AbortController
    const abortController = new AbortController()
    this.abortControllers.set(sessionId, abortController)

    // 历史记录
    const history: RoundHistory[] = []

    try {
      // 持久化用户消息节点
      try {
        const userNode: ChatNode = {
          id: uuidv4(),
          sessionId,
          parentId: null,
          role: 'user',
          content: query,
          round: 0,
          createdAt: Date.now(),
        }
        addNode(userNode)
        // 用问题的前30个字符作为会话标题
        updateSession(sessionId, { title: query.slice(0, 30) + (query.length > 30 ? '...' : '') })
      } catch (e) {
        console.warn('持久化用户消息失败:', e)
      }

      // 多轮辩论
      for (let round = 1; round <= rounds; round++) {
        console.log(`开始第 ${round}/${rounds} 轮辩论`)

        // 检查是否被中断
        if (abortController.signal.aborted) {
          console.log('辩论已被用户中断')
          break
        }

        // 为每个模型构建 Prompt
        const prompts = promptFactory.buildRoundPrompts(models, {
          round,
          originalQuery: query,
          previousRounds: history,
          fileContext: files,
          userIntervention: intervention,
        })

        // 并发调用所有模型
        const roundResponses = await this.runRound(
          sessionId,
          models,
          prompts,
          runtimeApiKeys,
          abortController.signal
        )

        // 保存本轮结果
        history.push({
          round,
          responses: roundResponses,
        })

        // 持久化每个模型的响应到数据库（含 Token 用量）
        try {
          roundResponses.forEach((content, modelId) => {
            if (content) {
              const usage = this._lastRoundUsage.get(modelId)
              const assistantNode: ChatNode = {
                id: uuidv4(),
                sessionId,
                parentId: null,
                role: 'assistant',
                modelId,
                content,
                round,
                tokenInput: usage?.inputTokens,
                tokenOutput: usage?.outputTokens,
                createdAt: Date.now(),
              }
              addNode(assistantNode)
            }
          })
        } catch (e) {
          console.warn('持久化模型响应失败:', e)
        }

        // 发送轮次完成事件
        this.sendEvent({
          type: 'round-complete',
          sessionId,
          round,
        })

        // 轮次之间等待 3 秒，让用户有时间阅读当前轮的结果
        if (round < rounds) {
          console.log(`等待 3 秒后开始第 ${round + 1} 轮...`)
          await new Promise(resolve => setTimeout(resolve, 3000))
        }

        // 检查是否被中断（等待期间可能用户按了停止）
        if (abortController.signal.aborted) {
          console.log('辩论在轮次间隔中被中断')
          break
        }

        // 检查是否需要压缩历史（为下一轮做准备）
        if (round < rounds) {
          for (const model of models) {
            if (tokenBudgetManager.needsCompression(history, model)) {
              console.log(`模型 ${model.name} 需要压缩历史`)
              // 执行压缩（简单版本，不使用 AI 摘要）
              const compressed = await tokenBudgetManager.compressHistory(history, model)
              history.length = 0
              history.push(...compressed)
              break
            }
          }
        }
      }

      // 辩论完成，生成最终裁决
      if (!abortController.signal.aborted && history.length > 0) {
        await this.generateVerdict(
          sessionId,
          query,
          models,
          history,
          files,
          runtimeApiKeys,
          abortController.signal,
          reportDetailLevel || 'standard'
        )
      }

      // 发送完成事件
      this.sendEvent({
        type: 'debate-complete',
        sessionId,
      })

    } catch (error) {
      console.error('辩论过程出错:', error)
      this.sendEvent({
        type: 'error',
        sessionId,
        error: String(error),
      })
    } finally {
      // 清理
      this.abortControllers.delete(sessionId)
    }
  }

  /**
   * 运行单轮辩论
   */
  private async runRound(
    sessionId: string,
    models: ModelConfig[],
    prompts: Map<string, import('../../../src/lib/types').Message[]>,
    apiKeys: Record<string, string>,
    signal: AbortSignal
  ): Promise<Map<string, string>> {
    const responses = new Map<string, string>()
    const responseBuffers = new Map<string, string>()
    // 收集每个模型的 Token 用量
    const responseUsage = new Map<string, TokenUsage>()

    // 为每个模型创建流式请求
    const streamPromises = models.map(async (model) => {
      console.log(`[辩论] 准备调用模型: ${model.name} (${model.id}), provider=${model.provider}, modelId=${model.modelId}`)
      
      const adapter = adapterManager.get(model.provider)
      if (!adapter) {
        const err = `未找到适配器: ${model.provider}`
        console.error(`[辩论] ${err}`)
        this.sendStreamChunk(sessionId, { modelId: model.id, content: '', done: true, error: err })
        return
      }

      const messages = prompts.get(model.id)
      if (!messages) {
        const err = `未找到 Prompt: ${model.id}, 可用keys: ${Array.from(prompts.keys()).join(', ')}`
        console.error(`[辩论] ${err}`)
        this.sendStreamChunk(sessionId, { modelId: model.id, content: '', done: true, error: err })
        return
      }

      // 优先使用前端传入的 API Key，其次从凭据服务获取
      const apiKey = apiKeys[model.provider] || await getApiKey(model.provider) || ''
      console.log(`[辩论] ${model.name} API Key: ${apiKey ? apiKey.substring(0, 10) + '...' : '(空)'}`)
      
      if (!apiKey && model.provider !== 'ollama') {
        const err = `${model.name} 的 API Key 未设置，请在设置中配置`
        console.error(`[辩论] ${err}`)
        this.sendStreamChunk(sessionId, { modelId: model.id, content: '', done: true, error: err })
        return
      }

      try {
        let buffer = ''
        console.log(`[辩论] 开始流式请求: ${model.name}, 消息数=${messages.length}, baseUrl=${model.baseUrl || '默认'}`)
        
        const generator = adapter.stream(messages, {
          apiKey,
          baseUrl: model.baseUrl,
          model: model.modelId,
          signal,
        })

        let chunkCount = 0
        for await (const chunk of generator) {
          if (signal.aborted) {
            console.log(`[辩论] ${model.name} 被中断`)
            break
          }

          chunkCount++
          buffer += chunk.content
          responseBuffers.set(model.id, buffer)

          // 发送流式数据到渲染进程
          this.sendStreamChunk(sessionId, {
            modelId: model.id,
            content: chunk.content,
            done: chunk.done,
            usage: chunk.usage,
            error: chunk.error,
          })

          if (chunk.error) {
            console.error(`[辩论] ${model.name} 返回错误: ${chunk.error}`)
          }

          if (chunk.done) {
            console.log(`[辩论] ${model.name} 完成, chunks=${chunkCount}, 内容长度=${buffer.length}`)
            responses.set(model.id, buffer)
            // 保存 Token 用量
            if (chunk.usage) {
              responseUsage.set(model.id, chunk.usage)
            }
          }
        }
        
        if (chunkCount === 0) {
          console.warn(`[辩论] ${model.name} 没有返回任何数据`)
        }
      } catch (error) {
        console.error(`[辩论] 模型 ${model.name} 调用异常:`, error)
        this.sendStreamChunk(sessionId, {
          modelId: model.id,
          content: '',
          done: true,
          error: `调用失败: ${String(error)}`,
        })
      }
    })

    // 等待所有模型完成
    await Promise.allSettled(streamPromises)

    // 将用量数据附加到 this 以供持久化使用
    this._lastRoundUsage = responseUsage

    return responses
  }

  // 临时存储上一轮的 Token 用量
  private _lastRoundUsage = new Map<string, TokenUsage>()

  /**
   * 生成最终裁决
   */
  private async generateVerdict(
    sessionId: string,
    query: string,
    models: ModelConfig[],
    history: RoundHistory[],
    files: import('../../../src/lib/types').FileAttachment[] | undefined,
    apiKeys: Record<string, string>,
    signal: AbortSignal,
    reportDetailLevel: import('../../../src/lib/types').ReportDetailLevel
  ): Promise<void> {
    // 选择上下文窗口最大的模型作为裁判
    const judge = models.reduce((prev, curr) => 
      curr.contextWindow > prev.contextWindow ? curr : prev
    )

    console.log(`使用 ${judge.name} 作为裁判生成最终裁决`)

    const adapter = adapterManager.get(judge.provider)
    if (!adapter) {
      console.error(`未找到裁判适配器: ${judge.provider}`)
      return
    }

    // 构建裁决 Prompt
    const verdictPrompt = promptFactory.buildVerdictPrompt({
      originalQuery: query,
      previousRounds: history,
      fileContext: files,
      reportDetailLevel,
    })

    const apiKey = apiKeys[judge.provider] || await getApiKey(judge.provider) || ''

    try {
      const generator = adapter.stream(verdictPrompt, {
        apiKey,
        baseUrl: judge.baseUrl,
        model: judge.modelId,
        signal,
      })

      let verdictBuffer = ''
      let verdictUsage: TokenUsage | undefined

      for await (const chunk of generator) {
        if (signal.aborted) break

        verdictBuffer += chunk.content
        if (chunk.usage) verdictUsage = chunk.usage

        // 使用特殊的 modelId 标识裁决
        this.sendStreamChunk(sessionId, {
          modelId: '__verdict__',
          content: chunk.content,
          done: chunk.done,
          usage: chunk.usage,
          error: chunk.error,
        })
      }

      // 持久化裁决内容
      try {
        if (verdictBuffer) {
          const verdictNode: ChatNode = {
            id: uuidv4(),
            sessionId,
            parentId: null,
            role: 'verdict',
            modelId: judge.id,
            content: verdictBuffer,
            round: history.length + 1,
            tokenInput: verdictUsage?.inputTokens,
            tokenOutput: verdictUsage?.outputTokens,
            createdAt: Date.now(),
          }
          addNode(verdictNode)
        }
      } catch (e) {
        console.warn('持久化裁决内容失败:', e)
      }
    } catch (error) {
      console.error('生成裁决失败:', error)
      this.sendStreamChunk(sessionId, {
        modelId: '__verdict__',
        content: '',
        done: true,
        error: String(error),
      })
    }
  }

  /**
   * 停止生成
   */
  stopGeneration(sessionId: string): void {
    const controller = this.abortControllers.get(sessionId)
    if (controller) {
      console.log('停止生成:', sessionId)
      controller.abort()
      this.abortControllers.delete(sessionId)
    }
  }

  /**
   * 发送流式数据块到渲染进程
   */
  private sendStreamChunk(sessionId: string, chunk: StreamChunk): void {
    if (this.mainWindow && !this.mainWindow.isDestroyed()) {
      this.mainWindow.webContents.send('debate-stream', {
        ...chunk,
        sessionId,
      })
    }
  }

  /**
   * 发送事件到渲染进程
   */
  private sendEvent(event: DebateEvent): void {
    if (this.mainWindow && !this.mainWindow.isDestroyed()) {
      this.mainWindow.webContents.send('debate-event', event)
    }
  }
}

// 导出单例
export const debateController = new DebateController()
