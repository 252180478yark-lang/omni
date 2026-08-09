import { proxyWorkbenchContext } from '../_context-proxy'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function POST(request: Request) {
  return proxyWorkbenchContext(request, true)
}
