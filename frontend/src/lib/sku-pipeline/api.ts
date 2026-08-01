import type { SkuOperationInput, SkuOperationOutput, SkuPipelineOperationId } from './operations'

export async function executeSkuOperation<T extends SkuPipelineOperationId>(
  operationId: T,
  input: SkuOperationInput<T>,
): Promise<SkuOperationOutput<T>> {
  const response = await fetch(`/api/omni/sku-pipeline/operations/${encodeURIComponent(operationId)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  const envelope = await response.json().catch(() => ({ success: false, error: 'invalid_json_response' })) as {
    success: boolean
    data?: SkuOperationOutput<T>
    error?: string
  }
  if (!response.ok || !envelope.success || envelope.data === undefined) {
    throw new Error(envelope.error || `operation_failed:${response.status}`)
  }
  return envelope.data
}
