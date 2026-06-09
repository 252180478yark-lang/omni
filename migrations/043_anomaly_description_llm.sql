-- 043: mvp_anomaly 加 description_llm
-- 异动引擎 _llm_one_liner 生成的一句话行动建议此前只写 mvp_decision_log，
-- diagnose / explain_anomaly 完全读不到（孤岛、白烧 token）。改写进本列，
-- explain_anomaly 以 engine_suggestion 带出，老板看异动时多一个候选行动方向。
ALTER TABLE mvp_anomaly ADD COLUMN IF NOT EXISTS description_llm TEXT;
COMMENT ON COLUMN mvp_anomaly.description_llm IS
  '异动引擎 LLM 一句话行动建议（fail-open 可空）；explain_anomaly 以 engine_suggestion 带出';
