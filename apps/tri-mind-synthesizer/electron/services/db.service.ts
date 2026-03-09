import path from 'path'
import { app, dialog } from 'electron'
import Database from 'better-sqlite3'
import { Session, ChatNode, ProviderConfig } from '../../src/lib/types'
import { v4 as uuidv4 } from 'uuid'

// 数据库实例
let db: Database.Database | null = null

/**
 * 初始化数据库
 */
export async function initDatabase(): Promise<void> {
  try {
    // 获取用户数据目录（已设置为项目目录下的 data 文件夹）
    const userDataPath = app.getPath('userData')
    
    // 确保目录存在
    const fs = await import('fs')
    if (!fs.existsSync(userDataPath)) {
      fs.mkdirSync(userDataPath, { recursive: true })
    }
    
    const dbPath = path.join(userDataPath, 'tri-mind.db')
    
    console.log('数据库路径:', dbPath)
    
    // 初始化 better-sqlite3 数据库
    db = new Database(dbPath)
    
    // 启用外键约束
    db.pragma('foreign_keys = ON')
    
    // 创建表结构
    createTables()
    
    console.log('数据库初始化完成')
  } catch (error) {
    console.error('数据库初始化失败:', error)
    dialog.showErrorBox('数据库错误', `初始化数据库失败，历史记录将无法保存。\n错误信息: ${error}\n路径: ${path.join(app.getPath('userData'), 'tri-mind.db')}`)
    // 尝试使用内存数据库作为后备
    try {
      db = new Database(':memory:')
      db.pragma('foreign_keys = ON')
      createTables()
      console.warn('已切换到内存存储模式')
    } catch (memError) {
      console.error('内存数据库初始化也失败:', memError)
    }
  }
}

/**
 * 获取数据库实例
 */
export function getDatabase(): Database.Database | null {
  return db
}

/**
 * 创建表结构
 */
function createTables(): void {
  if (!db) return

  // 会话表
  db.exec(`
    CREATE TABLE IF NOT EXISTS sessions (
      id TEXT PRIMARY KEY,
      title TEXT NOT NULL DEFAULT '新会话',
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL,
      config TEXT NOT NULL DEFAULT '{}'
    )
  `)

  // 对话节点表
  db.exec(`
    CREATE TABLE IF NOT EXISTS nodes (
      id TEXT PRIMARY KEY,
      session_id TEXT NOT NULL,
      parent_id TEXT,
      role TEXT NOT NULL,
      model_id TEXT,
      content TEXT NOT NULL,
      round INTEGER,
      token_input INTEGER DEFAULT 0,
      token_output INTEGER DEFAULT 0,
      created_at INTEGER NOT NULL,
      FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
    )
  `)

  // 配置表
  db.exec(`
    CREATE TABLE IF NOT EXISTS config (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    )
  `)

  // 创建索引
  db.exec(`
    CREATE INDEX IF NOT EXISTS idx_nodes_session ON nodes(session_id);
    CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent_id);
  `)
}

// ==================== 会话操作 ====================

/**
 * 创建新会话
 */
export function createSession(title: string = '新会话'): Session {
  const session: Session = {
    id: uuidv4(),
    title,
    createdAt: Date.now(),
    updatedAt: Date.now(),
    config: { models: [], rounds: 2 },
  }

  if (db) {
    const stmt = db.prepare(`
      INSERT INTO sessions (id, title, created_at, updated_at, config)
      VALUES (?, ?, ?, ?, ?)
    `)
    stmt.run(session.id, session.title, session.createdAt, session.updatedAt, JSON.stringify(session.config))
  }

  return session
}

/**
 * 获取会话
 */
export function getSession(id: string): Session | null {
  if (!db) return null

  const stmt = db.prepare('SELECT * FROM sessions WHERE id = ?')
  const row = stmt.get(id) as any
  
  if (!row) return null

  return {
    id: row.id,
    title: row.title,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    config: JSON.parse(row.config || '{}'),
  }
}

/**
 * 获取所有会话
 */
export function listSessions(): Session[] {
  if (!db) return []

  const stmt = db.prepare('SELECT * FROM sessions ORDER BY updated_at DESC')
  const rows = stmt.all() as any[]

  return rows.map(row => ({
    id: row.id,
    title: row.title,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    config: JSON.parse(row.config || '{}'),
  }))
}

/**
 * 更新会话
 */
export function updateSession(id: string, updates: Partial<Session>): boolean {
  if (!db) return false

  const session = getSession(id)
  if (!session) return false

  const newTitle = updates.title ?? session.title
  const newConfig = updates.config ?? session.config
  const updatedAt = Date.now()

  const stmt = db.prepare(`
    UPDATE sessions SET title = ?, config = ?, updated_at = ?
    WHERE id = ?
  `)
  stmt.run(newTitle, JSON.stringify(newConfig), updatedAt, id)

  return true
}

/**
 * 删除会话
 */
export function deleteSession(id: string): boolean {
  if (!db) return false

  const stmt = db.prepare('DELETE FROM sessions WHERE id = ?')
  const result = stmt.run(id)

  return result.changes > 0
}

// ==================== 节点操作 ====================

/**
 * 添加对话节点
 */
export function addNode(node: ChatNode): void {
  if (!db) return

  const stmt = db.prepare(`
    INSERT INTO nodes (id, session_id, parent_id, role, model_id, content, round, token_input, token_output, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `)
  stmt.run(
    node.id,
    node.sessionId,
    node.parentId,
    node.role,
    node.modelId,
    node.content,
    node.round,
    node.tokenInput || 0,
    node.tokenOutput || 0,
    node.createdAt
  )

  // 更新会话的更新时间
  updateSession(node.sessionId, {})
}

/**
 * 获取会话的所有节点
 */
export function getSessionNodes(sessionId: string): ChatNode[] {
  if (!db) return []

  const stmt = db.prepare('SELECT * FROM nodes WHERE session_id = ? ORDER BY created_at ASC')
  const rows = stmt.all(sessionId) as any[]

  return rows.map(row => ({
    id: row.id,
    sessionId: row.session_id,
    parentId: row.parent_id,
    role: row.role,
    modelId: row.model_id,
    content: row.content,
    round: row.round,
    tokenInput: row.token_input,
    tokenOutput: row.token_output,
    createdAt: row.created_at,
  }))
}

// ==================== 配置操作 ====================

/**
 * 保存配置
 */
export function saveConfig(key: string, value: unknown): void {
  if (!db) return

  const stmt = db.prepare(`
    INSERT OR REPLACE INTO config (key, value)
    VALUES (?, ?)
  `)
  stmt.run(key, JSON.stringify(value))
}

/**
 * 获取配置
 */
export function getConfig<T>(key: string, defaultValue: T): T {
  if (!db) return defaultValue

  const stmt = db.prepare('SELECT value FROM config WHERE key = ?')
  const row = stmt.get(key) as { value: string } | undefined

  if (!row) return defaultValue

  try {
    return JSON.parse(row.value) as T
  } catch {
    return defaultValue
  }
}

/**
 * 关闭数据库
 */
export function closeDatabase(): void {
  if (db) {
    db.close()
    db = null
    console.log('数据库已关闭')
  }
}
