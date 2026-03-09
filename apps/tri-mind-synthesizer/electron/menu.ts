import { Menu, BrowserWindow, MenuItemConstructorOptions } from 'electron'

export function buildAppMenu(mainWindow: BrowserWindow): Menu {
  const isMac = process.platform === 'darwin'

  const template: MenuItemConstructorOptions[] = [
    // macOS 应用菜单
    ...(isMac ? [{
      label: 'Tri-Mind Synthesizer',
      submenu: [
        { role: 'about' as const, label: '关于 Tri-Mind Synthesizer' },
        { type: 'separator' as const },
        { role: 'services' as const, label: '服务' },
        { type: 'separator' as const },
        { role: 'hide' as const, label: '隐藏' },
        { role: 'hideOthers' as const, label: '隐藏其他' },
        { role: 'unhide' as const, label: '显示全部' },
        { type: 'separator' as const },
        { role: 'quit' as const, label: '退出' },
      ],
    }] : []),
    
    // 文件菜单
    {
      label: '文件',
      submenu: [
        {
          label: '新建会话',
          accelerator: 'CmdOrCtrl+N',
          click: () => mainWindow.webContents.send('new-session'),
        },
        { type: 'separator' },
        {
          label: '导出辩论...',
          accelerator: 'CmdOrCtrl+Shift+E',
          click: () => mainWindow.webContents.send('export-debate'),
        },
        { type: 'separator' },
        isMac ? { role: 'close', label: '关闭窗口' } : { role: 'quit', label: '退出' },
      ],
    },
    
    // 编辑菜单
    {
      label: '编辑',
      submenu: [
        { role: 'undo', label: '撤销' },
        { role: 'redo', label: '重做' },
        { type: 'separator' },
        { role: 'cut', label: '剪切' },
        { role: 'copy', label: '复制' },
        { role: 'paste', label: '粘贴' },
        { type: 'separator' },
        { role: 'selectAll', label: '全选' },
      ],
    },
    
    // 视图菜单
    {
      label: '视图',
      submenu: [
        {
          label: '设置',
          accelerator: 'CmdOrCtrl+,',
          click: () => mainWindow.webContents.send('open-settings'),
        },
        { type: 'separator' },
        { role: 'toggleDevTools', label: '开发者工具' },
        { type: 'separator' },
        { role: 'resetZoom', label: '重置缩放' },
        { role: 'zoomIn', label: '放大' },
        { role: 'zoomOut', label: '缩小' },
        { type: 'separator' },
        { role: 'togglefullscreen', label: '全屏' },
      ],
    },
    
    // 窗口菜单
    {
      label: '窗口',
      submenu: [
        { role: 'minimize', label: '最小化' },
        ...(isMac ? [
          { type: 'separator' as const },
          { role: 'front' as const, label: '前置所有窗口' },
        ] : [
          { role: 'close' as const, label: '关闭' },
        ]),
      ],
    },
    
    // 帮助菜单
    {
      label: '帮助',
      submenu: [
        {
          label: '关于 Tri-Mind Synthesizer',
          click: () => {
            const { dialog } = require('electron')
            dialog.showMessageBox(mainWindow, {
              type: 'info',
              title: '关于',
              message: 'Tri-Mind Synthesizer',
              detail: '版本 1.0.0\n\n多模型辩论工具 - 让多个LLM针对同一问题进行并发对比、交叉质疑与综合裁决。',
            })
          },
        },
      ],
    },
  ]

  return Menu.buildFromTemplate(template)
}
