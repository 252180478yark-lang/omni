-- SP9 Reverse Material Decomposer

CREATE TABLE IF NOT EXISTS video_analysis.materials (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    material_type VARCHAR(20) NOT NULL,
    title TEXT,
    source_url TEXT,
    target_kb_id UUID NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    phase VARCHAR(40) NOT NULL DEFAULT 'queued',
    progress REAL NOT NULL DEFAULT 0,
    progress_message TEXT,
    error TEXT,
    retries INT NOT NULL DEFAULT 0,
    duration_sec REAL,
    unit_count INT NOT NULL DEFAULT 0,
    narrative_model TEXT,
    global_tone TEXT,
    bgm_json JSONB,
    file_paths JSONB NOT NULL DEFAULT '[]'::jsonb,
    cost_usd REAL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_va_materials_type ON video_analysis.materials(material_type);
CREATE INDEX IF NOT EXISTS idx_va_materials_status ON video_analysis.materials(status);
CREATE INDEX IF NOT EXISTS idx_va_materials_kb ON video_analysis.materials(target_kb_id);
CREATE INDEX IF NOT EXISTS idx_va_materials_created ON video_analysis.materials(created_at DESC);

CREATE TABLE IF NOT EXISTS video_analysis.material_units (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    material_id UUID NOT NULL REFERENCES video_analysis.materials(id) ON DELETE CASCADE,
    unit_index INT NOT NULL,
    unit_type VARCHAR(40) NOT NULL,
    start_sec REAL,
    end_sec REAL,
    image_index INT,
    keyframe_paths JSONB NOT NULL DEFAULT '[]'::jsonb,
    fields JSONB NOT NULL,
    prompt_pack JSONB NOT NULL,
    chunk_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_va_units_material ON video_analysis.material_units(material_id);
CREATE INDEX IF NOT EXISTS idx_va_units_type ON video_analysis.material_units(unit_type);

CREATE TABLE IF NOT EXISTS video_analysis.material_clusters (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    cluster_index INT NOT NULL,
    material_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    summary_json JSONB NOT NULL,
    target_kb_id UUID NOT NULL,
    chunk_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_va_clusters_kb ON video_analysis.material_clusters(target_kb_id);
