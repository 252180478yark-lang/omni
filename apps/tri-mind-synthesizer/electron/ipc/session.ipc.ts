import { IpcMain } from 'electron'
import * as dbService from '../services/db.service'

export function registerSessionIPC(ipcMain: IpcMain) {
  // 新建会话
  ipcMain.handle('new-session', async () => {
    try {
      const session = dbService.createSession()
      console.log('创建新会话:', session.id)
      return { success: true, data: session }
    } catch (error) {
      console.error('创建会话失败:', error)
      return { success: false, error: String(error) }
    }
  })

  // 加载会话
  ipcMain.handle('load-session', async (_event, sessionId: string) => {
    try {
      const session = dbService.getSession(sessionId)
      if (!session) {
        return { success: false, error: '会话不存在' }
      }
      
      // 加载会话的消息节点
      const nodes = dbService.getSessionNodes(sessionId)
      return { success: true, data: { session, nodes } }
    } catch (error) {
      console.error('加载会话失败:', error)
      return { success: false, error: String(error) }
    }
  })

  // 获取会话列表
  ipcMain.handle('list-sessions', async () => {
    try {
      const list = dbService.listSessions()
      return { success: true, data: list }
    } catch (error) {
      console.error('获取会话列表失败:', error)
      return { success: false, error: String(error) }
    }
  })

  // 删除会话
  ipcMain.handle('delete-session', async (_event, sessionId: string) => {
    try {
      dbService.deleteSession(sessionId)
      console.log('删除会话:', sessionId)
      return { success: true }
    } catch (error) {
      console.error('删除会话失败:', error)
      return { success: false, error: String(error) }
    }
  })

  // 更新会话标题
  ipcMain.handle('update-session-title', async (_event, { sessionId, title }: { sessionId: string; title: string }) => {
    try {
      const success = dbService.updateSession(sessionId, { title })
      if (!success) {
        return { success: false, error: '会话不存在' }
      }
      return { success: true }
    } catch (error) {
      console.error('更新会话标题失败:', error)
      return { success: false, error: String(error) }
    }
  })
}
