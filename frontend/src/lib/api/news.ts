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

export interface ArticleFilters {
  status?: string;
  source?: string;
  language?: string;
  tag?: string | null;
  search?: string;
  sortBy?: 'fetched_at' | 'ai_relevance_score' | 'published_at';
  sortOrder?: 'asc' | 'desc';
  page?: number;
  pageSize?: number;
}

export interface ArchiveFilters {
  source?: string;
  language?: string;
  tags?: string[];
  search?: string;
  isStarred?: boolean | null;
  dateFrom?: string | null;
  dateTo?: string | null;
  sortBy?: 'archived_at' | 'published_at' | 'ai_relevance_score';
  sortOrder?: 'asc' | 'desc';
  page?: number;
  pageSize?: number;
}

async function fetchJson(url: string, options: RequestInit = {}) {
  const headers = {
    'Content-Type': 'application/json',
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
    fetchJson(`${BASE_URL}/fetch`, {
      method: 'POST',
      body: JSON.stringify(params || {}),
    }),

  getJobStatus: (jobId: string): Promise<JobStatusResponse> =>
    fetchJson(`${BASE_URL}/fetch/${jobId}`),

  getArticles: (filters: ArticleFilters): Promise<ArticleListResponse> => {
    const query = new URLSearchParams();
    const normalized = {
      status: filters.status,
      source: filters.source,
      language: filters.language,
      tag: filters.tag,
      search: filters.search,
      sort_by: filters.sortBy,
      sort_order: filters.sortOrder,
      page: filters.page,
      page_size: filters.pageSize,
    };

    Object.entries(normalized).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        query.append(key, String(value));
      }
    });
    return fetchJson(`${BASE_URL}/articles?${query.toString()}`);
  },

  patchArticle: (id: string, patch: Partial<Article>): Promise<void> =>
    fetchJson(`${BASE_URL}/articles/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  batchArticles: (articleIds: string[], action: 'archive' | 'dismiss'): Promise<unknown> =>
    fetchJson(`${BASE_URL}/articles/batch`, {
      method: 'POST',
      body: JSON.stringify({ article_ids: articleIds, action }),
    }),

  getArchive: (filters: ArchiveFilters): Promise<ArticleListResponse> => {
    const query = new URLSearchParams();
    const normalized = {
      source: filters.source,
      language: filters.language,
      tags: filters.tags,
      search: filters.search,
      is_starred: filters.isStarred,
      date_from: filters.dateFrom,
      date_to: filters.dateTo,
      sort_by: filters.sortBy,
      sort_order: filters.sortOrder,
      page: filters.page,
      page_size: filters.pageSize,
    };

    Object.entries(normalized).forEach(([key, value]) => {
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
    return fetchJson(`${BASE_URL}/archive?${query.toString()}`);
  },

  getArchiveStats: (): Promise<ArchiveStats> =>
    fetchJson(`${BASE_URL}/archive/stats`),

  getAvailableTags: (): Promise<{ tags: { tag: string; count: number }[] }> =>
    fetchJson(`${BASE_URL}/archive/tags`),

  retryKbPush: (articleIds: string[]): Promise<unknown> =>
    fetchJson(`${BASE_URL}/archive/retry-kb`, {
      method: 'POST',
      body: JSON.stringify({ article_ids: articleIds }),
    }),
};
