export interface Article {
  id: string;
  title: string;
  url: string;
  source: 'serper' | 'bocha' | 'tianapi';
  source_name: string | null;
  ai_summary: string | null;
  raw_snippet: string | null;
  ai_tags: string[];
  ai_relevance_score: number;
  status: 'pending' | 'archived' | 'dismissed';
  is_starred: boolean;
  language: 'zh' | 'en';
  published_at: string | null;
  fetched_at: string;
  kb_doc_id?: string | null;
}

export interface ArticleListResponse {
  total: number;
  page: number;
  page_size: number;
  items: Article[];
}

export interface FetchParams {
  sources?: string[];
  keywords_override?: string[] | null;
  freshness_override?: string | null;
}

export interface FetchResponse {
  job_id: string;
  status: string;
  message: string;
}

export interface JobStatusResponse {
  job_id: string;
  status: 'running' | 'completed' | 'failed';
  sources_used: string[];
  total_fetched: number;
  after_dedup: number;
  after_enrich: number;
  started_at: string;
  finished_at: string | null;
}

export interface ArchiveStats {
  total_archived: number;
  by_source: Record<string, number>;
  top_tags: { tag: string; count: number }[];
  recent_7d_count: number;
  kb_synced_count: number;
  kb_pending_count: number;
}

const BASE_URL = '/api/v1/news';

async function fetchWithAuth(url: string, options: RequestInit = {}) {
  const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.headers,
  };

  const response = await fetch(url, { ...options, headers });
  if (!response.ok) {
    let errorMsg = 'API Request Failed';
    try {
      const errData = await response.json();
      errorMsg = errData.detail || errorMsg;
    } catch {
      // ignore
    }
    throw new Error(errorMsg);
  }
  return response.json();
}

export const newsApi = {
  triggerFetch: (params?: FetchParams): Promise<FetchResponse> => 
    fetchWithAuth(`${BASE_URL}/fetch`, {
      method: 'POST',
      body: JSON.stringify(params || {}),
    }),

  getJobStatus: (jobId: string): Promise<JobStatusResponse> =>
    fetchWithAuth(`${BASE_URL}/fetch/${jobId}`),

  getArticles: (filters: Record<string, string | number | boolean | null | undefined>): Promise<ArticleListResponse> => {
    const query = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        query.append(key, String(value));
      }
    });
    return fetchWithAuth(`${BASE_URL}/articles?${query.toString()}`);
  },

  patchArticle: (id: string, patch: Partial<Article>): Promise<void> =>
    fetchWithAuth(`${BASE_URL}/articles/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  batchArticles: (articleIds: string[], action: 'archive' | 'dismiss'): Promise<unknown> =>
    fetchWithAuth(`${BASE_URL}/articles/batch`, {
      method: 'POST',
      body: JSON.stringify({ article_ids: articleIds, action }),
    }),

  getArchive: (filters: Record<string, string | number | boolean | string[] | null | undefined>): Promise<ArticleListResponse> => {
    const query = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        // Handle array of tags
        if (Array.isArray(value)) {
          if (value.length > 0) {
            query.append(key, value.join(','));
          }
        } else {
          query.append(key, String(value));
        }
      }
    });
    return fetchWithAuth(`${BASE_URL}/archive?${query.toString()}`);
  },

  getArchiveStats: (): Promise<ArchiveStats> =>
    fetchWithAuth(`${BASE_URL}/archive/stats`),

  getAvailableTags: (): Promise<{ tags: { tag: string; count: number }[] }> =>
    fetchWithAuth(`${BASE_URL}/archive/tags`),

  retryKbPush: (articleIds: string[]): Promise<unknown> =>
    fetchWithAuth(`${BASE_URL}/archive/retry-kb`, {
      method: 'POST',
      body: JSON.stringify({ article_ids: articleIds }),
    }),
};
