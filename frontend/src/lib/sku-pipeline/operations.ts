export const SKU_PIPELINE_OPERATIONS = {
  sellingPointsGenerate: 'sku.selling-points.generate',
  audienceMatchGenerate: 'sku.audience-match.generate',
  keywordPackGenerate: 'sku.keyword-pack.generate',
  audiencePackGenerate: 'sku.audience-pack.generate',
  creativePackGenerate: 'sku.creative-pack.generate',
  characterSheetsGenerate: 'sku.character-sheets.generate',
  storyboardGenerate: 'sku.storyboard.generate',
  videoGenerate: 'sku.video.generate',
  videoAnchorGenerate: 'sku.video-anchor.generate',
  audiencePortraitGenerate: 'sku.audience-portrait.generate',
  directorBriefGenerate: 'sku.director-brief.generate',
  matrixRunsList: 'sku.matrix-runs.list',
  matrixRunGet: 'sku.matrix-run.get',
  audienceRunsList: 'sku.audience-runs.list',
  audienceRunGet: 'sku.audience-run.get',
  audienceRecordsList: 'sku.audience-records.list',
  audienceRecordGet: 'sku.audience-record.get',
  adopt: 'sku.pipeline.adopt',
  lineageGet: 'sku.lineage.get',
  nodeArchive: 'sku.node.archive',
  assetsList: 'sku.assets.list',
  audiencePackGet: 'sku.audience-pack.get',
  audiencePortraitsList: 'sku.audience-portraits.list',
  audiencePortraitGet: 'sku.audience-portrait.get',
  adMetricsRecord: 'sku.ad-metrics.record',
  assetPerformanceList: 'sku.asset-performance.list',
  assetLineageGet: 'sku.asset-lineage.get',
} as const

export type SkuPipelineOperationId = typeof SKU_PIPELINE_OPERATIONS[keyof typeof SKU_PIPELINE_OPERATIONS]

const OPERATION_IDS = new Set<string>(Object.values(SKU_PIPELINE_OPERATIONS))

export function isSkuPipelineOperationId(value: string): value is SkuPipelineOperationId {
  return OPERATION_IDS.has(value)
}

export interface SellingPointsInput {
  sku_id: string
  user_initial_points?: string
  user_reviews?: string
  kb_context?: string | null
  extra_context?: string | null
}

export interface SellingPointsOutput {
  ok: boolean
  result?: { matrix_md: string; sku_id: string; matrix_run_id?: string | null }
  trace?: { model_provider: string; model: string; final_prompt: string; params: Record<string, unknown>; cost_estimate: string }
  error?: string
  hint?: string
}

export type SkuOperationInput<T extends SkuPipelineOperationId> =
  T extends 'sku.selling-points.generate' ? SellingPointsInput : Record<string, unknown>

export type SkuOperationOutput<T extends SkuPipelineOperationId> =
  T extends 'sku.selling-points.generate' ? SellingPointsOutput : unknown
