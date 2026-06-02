import { loadEnvConfig } from '@next/env'
// 必须在 import ws-handler 前加载 .env.local, 否则 ws-handler.ts 顶层创建的
// pg.Pool 拿到的 process.env.PGPASSWORD 还是 undefined → 走默认 'omni_pass' 错密码
loadEnvConfig(process.cwd())

import { createServer } from 'node:http'
import { parse } from 'node:url'
import next from 'next'
import { WebSocketServer } from 'ws'
import { attachWsHandler } from './src/lib/agent-chat/ws-handler'

const dev = process.env.NODE_ENV !== 'production'
const hostname = '127.0.0.1'
const port = parseInt(process.env.PORT || '3000', 10)

const app = next({ dev, hostname, port })
const handle = app.getRequestHandler()

app.prepare().then(() => {
  const server = createServer((req, res) => {
    const parsedUrl = parse(req.url || '', true)
    handle(req, res, parsedUrl)
  })

  const wss = new WebSocketServer({ noServer: true })
  wss.on('connection', (ws) => {
    attachWsHandler(ws)
  })

  server.on('upgrade', (req, socket, head) => {
    if (req.url === '/ws/agent-chat') {
      wss.handleUpgrade(req, socket, head, (ws) => {
        wss.emit('connection', ws, req)
      })
    } else {
      socket.destroy()
    }
  })

  server.listen(port, hostname, () => {
    // eslint-disable-next-line no-console
    console.log(`> Ready on http://${hostname}:${port}`)
  })
})
