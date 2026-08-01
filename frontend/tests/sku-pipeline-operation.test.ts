import { describe, expect, it } from 'vitest'

import { isSkuPipelineOperationId, SKU_PIPELINE_OPERATIONS } from '@/lib/sku-pipeline/operations'

describe('closed SKU Pipeline operation registry', () => {
  it('accepts declared operations and rejects arbitrary tool names', () => {
    expect(isSkuPipelineOperationId(SKU_PIPELINE_OPERATIONS.sellingPointsGenerate)).toBe(true)
    expect(isSkuPipelineOperationId('generate_selling_points_matrix')).toBe(false)
    expect(isSkuPipelineOperationId('../../app.mcp.tools.media')).toBe(false)
  })
})
