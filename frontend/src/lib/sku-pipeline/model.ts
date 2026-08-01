import type { SkuPipelineOperationId } from './operations'

export type { SellingPointsInput, SellingPointsOutput, SkuPipelineOperationId } from './operations'

export interface SkuPipelineStep {
  id: string
  title: string
  state: 'idle' | 'running' | 'success' | 'error'
  operationId?: SkuPipelineOperationId
}
