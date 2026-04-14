import html2canvas from 'html2canvas'
import { jsPDF } from 'jspdf'

/** A4 内边距（mm），与原先 html2pdf 配置一致 */
const MARGIN_MM = { top: 12, left: 12, bottom: 12, right: 12 }
const A4_MM = { w: 210, h: 297 }
const INNER_MM = {
  w: A4_MM.w - MARGIN_MM.left - MARGIN_MM.right,
  h: A4_MM.h - MARGIN_MM.top - MARGIN_MM.bottom,
}
/** 单页内容区宽高比（高/宽），用于按宽度切片 canvas */
const INNER_RATIO = INNER_MM.h / INNER_MM.w

export type CaptureToPdfOptions = {
  /** html2canvas 缩放，长文可降到 1.5 减轻画布超限风险 */
  scale?: number
  jpegQuality?: number
}

/**
 * 将已挂载在 DOM 中的节点渲染为多页 PDF（不经过 html2pdf 的 opacity:0 中间层，避免空白页）。
 */
export async function captureElementToPdf(
  element: HTMLElement,
  filename: string,
  options: CaptureToPdfOptions = {},
): Promise<void> {
  const scale = options.scale ?? 2
  const jpegQuality = options.jpegQuality ?? 0.92

  const canvas = await html2canvas(element, {
    scale,
    useCORS: true,
    backgroundColor: '#ffffff',
    logging: false,
    onclone: (clonedDoc) => {
      clonedDoc.documentElement.style.backgroundColor = '#ffffff'
      clonedDoc.body.style.backgroundColor = '#ffffff'
      clonedDoc.body.style.color = '#111111'
      clonedDoc.body.style.margin = '0'
    },
  })

  const pdf = new jsPDF({ unit: 'mm', format: 'a4', orientation: 'portrait' })

  const pxFullHeight = canvas.height
  const pxPageHeight = Math.max(1, Math.floor(canvas.width * INNER_RATIO))
  const nPages = Math.max(1, Math.ceil(pxFullHeight / pxPageHeight))

  const pageCanvas = document.createElement('canvas')
  const pageCtx = pageCanvas.getContext('2d')
  if (!pageCtx) throw new Error('无法创建 Canvas 上下文')
  pageCanvas.width = canvas.width

  for (let page = 0; page < nPages; page++) {
    const isLast = page === nPages - 1
    const remainder = pxFullHeight % pxPageHeight
    let sliceH = pxPageHeight
    if (isLast && remainder !== 0) {
      sliceH = remainder
    }
    pageCanvas.height = sliceH

    pageCtx.fillStyle = '#ffffff'
    pageCtx.fillRect(0, 0, pageCanvas.width, sliceH)
    pageCtx.drawImage(canvas, 0, page * pxPageHeight, pageCanvas.width, sliceH, 0, 0, pageCanvas.width, sliceH)

    const pageHeightMm = (pageCanvas.height * INNER_MM.w) / pageCanvas.width

    if (page > 0) pdf.addPage()
    const imgData = pageCanvas.toDataURL('image/jpeg', jpegQuality)
    pdf.addImage(imgData, 'JPEG', MARGIN_MM.left, MARGIN_MM.top, INNER_MM.w, pageHeightMm)
  }

  pdf.save(filename)
}
