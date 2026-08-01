'use client'

import { useState } from 'react'
import { executeSkuOperation } from '../api'
import type { SkuOperationInput, SkuOperationOutput, SkuPipelineOperationId } from '../operations'

export function useSkuOperation<T extends SkuPipelineOperationId>(operationId: T) {
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [data, setData] = useState<SkuOperationOutput<T> | null>(null)

  const execute = async (input: SkuOperationInput<T>) => {
    setRunning(true)
    setError('')
    try {
      const value = await executeSkuOperation(operationId, input)
      setData(value)
      return value
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
      throw reason
    } finally {
      setRunning(false)
    }
  }

  return { execute, running, error, data }
}
