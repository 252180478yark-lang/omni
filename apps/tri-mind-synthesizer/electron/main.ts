import { app, BrowserWindow, ipcMain, Menu } from 'electron'
import path from 'path'
import { buildAppMenu } from './menu'
import { registerDebateIPC } from './ipc/debate.ipc'
import { registerConfigIPC } from './ipc/config.ipc'
import { registerFileIPC } from './ipc/file.ipc'
import { registerSessionIPC } from './ipc/session.ipc'
import { initDatabase, closeDatabase } from './services/db.service'

// 开发环境标识
const isDev = !app.isPackaged

// 设置用户数据目录到项目文件夹
if (isDev) {
  const projectDataPath = path.join(__dirname, '..', 'data')
  app.setPath('userData', projectDataPath)
  app.setPath('logs', path.join(projectDataPath, 'logs'))
  app.setPath('temp', path.join(projectDataPath, 'temp'))
  app.setPath('cache', path.join(projectDataPath, 'cache'))
}

let mainWindow: BrowserWindow | null = null

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    title: 'Tri-Mind Synthesizer',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false, // 需要访问系统API
    },
    show: false,
    backgroundColor: '#0a0a0a',
  })

  // 窗口准备好后再显示，避免白屏
  mainWindow.once('ready-to-show', () => {
    mainWindow?.show()
  })

  // 设置应用菜单
  const menu = buildAppMenu(mainWindow)
  Menu.setApplicationMenu(menu)

  // 加载页面
  if (isDev) {
    mainWindow.loadURL('http://localhost:5173')
    // 开发环境自动打开开发者工具
    mainWindow.webContents.openDevTools()
  } else {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'))
  }

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

// 注册所有IPC处理器
function registerIPCHandlers() {
  registerDebateIPC(ipcMain)
  registerConfigIPC(ipcMain)
  registerFileIPC(ipcMain)
  registerSessionIPC(ipcMain)
}

// 应用初始化
app.whenReady().then(async () => {
  // 初始化数据库
  await initDatabase()
  
  // 注册IPC处理器
  registerIPCHandlers()
  
  // 创建窗口
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

// 应用退出前关闭数据库
app.on('before-quit', () => {
  closeDatabase()
})

// 获取主窗口的辅助函数（供IPC使用）
export function getMainWindow(): BrowserWindow | null {
  return mainWindow
}
