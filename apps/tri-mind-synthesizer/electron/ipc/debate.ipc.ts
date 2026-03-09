import { IpcMain } from 'electron'
import { DebateParams } from '../../src/lib/types'
import { getMainWindow } from '../main'
import { debateController } from '../services/llm/debate-controller'

export function registerDebateIPC(ipcMain: IpcMain) {
  // 开始辩论
  ipcMain.handle('start-debate', async (_event, params: DebateParams) => {
    try {
      const mainWindow = getMainWindow()
      if (!mainWindow) {
        throw new Error('主窗口未初始化')
      }

      // 设置主窗口引用
      debateController.setMainWindow(mainWindow)

      console.log('开始辩论:', params.query)
      console.log('参与模型:', params.models.map(m => m.name).join(', '))
      console.log('辩论轮数:', params.rounds)

      // 异步启动辩论（不阻塞IPC响应）
      debateController.runDebate(params).catch(error => {
        console.error('辩论过程出错:', error)
        mainWindow.webContents.send('debate-stream', {
          sessionId: params.sessionId,
          modelId: '__error__',
          content: '',
          done: true,
          error: String(error),
        })
      })

      return { success: true }
    } catch (error) {
      console.error('辩论启动失败:', error)
      return { success: false, error: String(error) }
    }
  })

  // 停止生成
  ipcMain.handle('stop-generation', async (_event, sessionId: string) => {
    try {
      console.log('停止生成:', sessionId)
      debateController.stopGeneration(sessionId)
      return { success: true }
    } catch (error) {
      console.error('停止生成失败:', error)
      return { success: false, error: String(error) }
    }
  })
}
