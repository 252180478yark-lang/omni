请基于以下四个彼此隔离的上游事实区生成恰好两条桥接候选。

## SKU 事实（产品证据只可引用此区）
@@SKU_FACTS_JSON@@

## 卖点矩阵证据（产品证据只可引用此区）
@@MATRIX_EVIDENCE_JSON@@

## 人群记录与画像证据（痛点证据只可引用此区）
@@PORTRAIT_RECORD_EVIDENCE_JSON@@

## 圈包校准（只调演员气质、语言、视觉质感；不可替代痛点证据）
@@PACK_CALIBRATION_JSON@@

再次确认：只输出一个 JSON 根对象，bridges 恰好 2 条；两条只改变 trigger_scene、pain_point、pain_consequence，固定事实必须完全相同。
