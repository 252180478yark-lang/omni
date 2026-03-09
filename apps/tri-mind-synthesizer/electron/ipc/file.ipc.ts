import { IpcMain, dialog } from 'electron'
import { SaveFileParams, ExportDebateParams } from '../../src/lib/types'
import fs from 'fs/promises'
import { getMainWindow } from '../main'
import * as exportService from '../services/export.service'
import * as dbService from '../services/db.service'
import { parseFiles, getSupportedExtensions } from '../utils/file-parser'

export function registerFileIPC(ipcMain: IpcMain) {
  // 保存文件
  ipcMain.handle('save-file', async (_event, params: SaveFileParams) => {
    try {
      const mainWindow = getMainWindow()
      if (!mainWindow) {
        throw new Error('主窗口未初始化')
      }

      const { canceled, filePath } = await dialog.showSaveDialog(mainWindow, {
        defaultPath: params.defaultName,
        filters: [
          { name: '所有文件', extensions: [params.extension] },
        ],
      })

      if (canceled || !filePath) {
        return { success: true, data: null }
      }

      await fs.writeFile(filePath, params.content, 'utf-8')
      return { success: true, data: { path: filePath } }
    } catch (error) {
      console.error('保存文件失败:', error)
      return { success: false, error: String(error) }
    }
  })

  // 导出辩论记录
  ipcMain.handle('export-debate', async (_event, params: ExportDebateParams) => {
    try {
      const mainWindow = getMainWindow()
      if (!mainWindow) {
        throw new Error('主窗口未初始化')
      }

      // 获取会话信息
      const session = dbService.getSession(params.sessionId)
      
      // 生成文件名
      const defaultFilename = exportService.generateExportFilename(session, params.format)
      const filterName = params.format === 'md' ? 'Markdown' : 'JSON'

      const { canceled, filePath } = await dialog.showSaveDialog(mainWindow, {
        defaultPath: defaultFilename,
        filters: [
          { name: filterName, extensions: [params.format] },
        ],
      })

      if (canceled || !filePath) {
        return { success: true, data: null }
      }

      // 根据格式导出内容
      const content = params.format === 'md'
        ? exportService.exportToMarkdown(params.sessionId)
        : exportService.exportToJSON(params.sessionId)

      await fs.writeFile(filePath, content, 'utf-8')
      console.log('导出成功:', filePath)
      
      return { success: true, data: { path: filePath } }
    } catch (error) {
      console.error('导出失败:', error)
      return { success: false, error: String(error) }
    }
  })

  // 选择并解析文件
  ipcMain.handle('open-files', async () => {
    try {
      const mainWindow = getMainWindow()
      if (!mainWindow) {
        throw new Error('主窗口未初始化')
      }

      const extensions = getSupportedExtensions().map(ext => ext.replace('.', ''))

      const { canceled, filePaths } = await dialog.showOpenDialog(mainWindow, {
        properties: ['openFile', 'multiSelections'],
        filters: [
          { name: '支持的文件', extensions },
          { name: '所有文件', extensions: ['*'] },
        ],
      })

      if (canceled || filePaths.length === 0) {
        return { success: true, data: [] }
      }

      const attachments = await parseFiles(filePaths)
      return { success: true, data: attachments }
    } catch (error) {
      console.error('打开文件失败:', error)
      return { success: false, error: String(error) }
    }
  })
}
