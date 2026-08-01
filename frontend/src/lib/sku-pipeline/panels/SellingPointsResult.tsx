'use client'

import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ChevronDown, ChevronRight } from 'lucide-react'

import OutputFeedback from '@/components/OutputFeedback'
import { Badge } from '@/components/ui/badge'

interface SellingPointsResultProps {
  matrixMarkdown: string
  matrixRunId?: string | null
  finalPrompt?: string | null
}

/** Presentational boundary for the selling-points operation result. */
export function SellingPointsResult({
  matrixMarkdown,
  matrixRunId,
  finalPrompt,
}: SellingPointsResultProps) {
  const [showPrompt, setShowPrompt] = useState(true)

  return (
    <>
      {matrixRunId && (
        <div className="mb-3 flex items-center gap-2 text-xs">
          <Badge variant="outline" className="text-xs">已落库</Badge>
          <span className="text-muted-foreground">
            matrix_run_id: <code className="text-[10px]">{matrixRunId.slice(0, 8)}…</code>
            <span className="ml-2">step 3 会自动挂这个 id</span>
          </span>
        </div>
      )}

      <div className="prose prose-sm max-w-none dark:prose-invert">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{matrixMarkdown}</ReactMarkdown>
      </div>

      {finalPrompt && (
        <div className="mt-6 border-t pt-4">
          <button
            className="flex items-center gap-1 text-sm font-medium"
            onClick={() => setShowPrompt(value => !value)}
            type="button"
          >
            {showPrompt ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            Final Prompt
          </button>
          {showPrompt && (
            <pre className="mt-2 whitespace-pre-wrap rounded bg-muted p-3 text-xs">{finalPrompt}</pre>
          )}
        </div>
      )}

      <OutputFeedback toolName="generate_selling_points_matrix" />
    </>
  )
}
