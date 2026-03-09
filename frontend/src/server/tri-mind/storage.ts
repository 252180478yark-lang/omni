import { v4 as uuidv4 } from 'uuid'
import type { ChatNode, Session } from './types'

/**
 * 简单的内存存储
 * 使用 Map 存储 sessions 和 nodes，无 SQLite 依赖
 */
class InMemoryStorage {
  private sessions = new Map<string, Session>()
  private nodes = new Map<string, ChatNode>()
  private nodesBySession = new Map<string, string[]>() // sessionId -> nodeIds

  newSession(): Session {
    const id = uuidv4()
    const now = Date.now()
    const session: Session = {
      id,
      title: '新会话',
      createdAt: now,
      updatedAt: now,
      config: { models: [], rounds: 2 },
    }
    this.sessions.set(id, session)
    this.nodesBySession.set(id, [])
    return session
  }

  listSessions(): Session[] {
    return Array.from(this.sessions.values()).sort((a, b) => b.updatedAt - a.updatedAt)
  }

  deleteSession(sessionId: string): void {
    const nodeIds = this.nodesBySession.get(sessionId) || []
    nodeIds.forEach((id) => this.nodes.delete(id))
    this.nodesBySession.delete(sessionId)
    this.sessions.delete(sessionId)
  }

  addNode(node: ChatNode): void {
    this.nodes.set(node.id, node)
    const list = this.nodesBySession.get(node.sessionId) || []
    list.push(node.id)
    this.nodesBySession.set(node.sessionId, list)
  }

  updateSession(sessionId: string, updates: Partial<Pick<Session, 'title' | 'updatedAt'>>): void {
    const existing = this.sessions.get(sessionId)
    if (existing) {
      this.sessions.set(sessionId, { ...existing, ...updates, updatedAt: Date.now() })
    } else {
      this.sessions.set(sessionId, {
        id: sessionId,
        title: updates.title ?? 'New Session',
        createdAt: Date.now(),
        updatedAt: Date.now(),
      })
    }
  }

  getSession(sessionId: string): Session | undefined {
    return this.sessions.get(sessionId)
  }

  getNodesBySession(sessionId: string): ChatNode[] {
    const ids = this.nodesBySession.get(sessionId) || []
    return ids.map((id) => this.nodes.get(id)).filter((n): n is ChatNode => !!n)
  }

  clear(): void {
    this.sessions.clear()
    this.nodes.clear()
    this.nodesBySession.clear()
  }
}

export const storage = new InMemoryStorage()
