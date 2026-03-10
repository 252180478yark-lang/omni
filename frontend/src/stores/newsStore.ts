import { create } from 'zustand';
import { Article, ArchiveStats, FetchParams, newsApi } from '@/lib/api/news';

interface ArchiveSearchFilters {
  tags: string[];
  source: string;
  language: string;
  dateFrom: string | null;
  dateTo: string | null;
  search: string;
  isStarred: boolean | null;
  sortBy: 'archived_at' | 'published_at' | 'ai_relevance_score';
  sortOrder: 'asc' | 'desc';
}

interface NewsState {
  // Fetch Status
  fetchJobId: string | null;
  fetchStatus: 'idle' | 'fetching' | 'enriching' | 'completed' | 'failed';
  fetchProgress: { total: number; deduped: number; enriched: number };

  // Article List
  articles: Article[];
  totalCount: number;
  currentPage: number;

  // Filters
  filters: {
    status: 'pending' | 'archived' | 'dismissed' | 'all';
    source: string;
    language: string;
    tag: string | null;
    search: string;
    sortBy: 'fetched_at' | 'ai_relevance_score';
    sortOrder: 'asc' | 'desc';
  };

  // Batch Selection
  selectedIds: Set<string>;

  // Archive Search
  archiveFilters: ArchiveSearchFilters;
  archiveResults: Article[];
  archiveTotalCount: number;
  archiveCurrentPage: number;
  availableTags: { tag: string; count: number }[];
  archiveStats: ArchiveStats | null;

  // Actions
  triggerFetch: (params?: FetchParams) => Promise<void>;
  pollJobStatus: (jobId: string) => Promise<void>;
  loadArticles: () => Promise<void>;
  updateArticle: (id: string, patch: Partial<Article>) => Promise<void>;
  batchAction: (action: 'archive' | 'dismiss') => Promise<void>;
  toggleSelect: (id: string) => void;
  selectAll: () => void;
  clearSelection: () => void;
  setFilter: (key: string, value: string | number | boolean | null) => void;

  // Archive Actions
  loadArchiveStats: () => Promise<void>;
  loadAvailableTags: () => Promise<void>;
  searchArchive: () => Promise<void>;
  setArchiveFilter: (key: string, value: string | number | boolean | string[] | null) => void;
  addTagFilter: (tag: string) => void;
  removeTagFilter: (tag: string) => void;
  resetArchiveFilters: () => void;
  retryKbPush: (articleIds: string[]) => Promise<void>;
}

export const useNewsStore = create<NewsState>((set, get) => ({
  fetchJobId: null,
  fetchStatus: 'idle',
  fetchProgress: { total: 0, deduped: 0, enriched: 0 },

  articles: [],
  totalCount: 0,
  currentPage: 1,

  filters: {
    status: 'pending',
    source: 'all',
    language: 'all',
    tag: null,
    search: '',
    sortBy: 'fetched_at',
    sortOrder: 'desc',
  },

  selectedIds: new Set(),

  archiveFilters: {
    tags: [],
    source: 'all',
    language: 'all',
    dateFrom: null,
    dateTo: null,
    search: '',
    isStarred: null,
    sortBy: 'archived_at',
    sortOrder: 'desc',
  },
  archiveResults: [],
  archiveTotalCount: 0,
  archiveCurrentPage: 1,
  availableTags: [],
  archiveStats: null,

  triggerFetch: async (params) => {
    try {
      set({ fetchStatus: 'fetching', fetchProgress: { total: 0, deduped: 0, enriched: 0 } });
      const res = await newsApi.triggerFetch(params);
      set({ fetchJobId: res.job_id });
      // Start polling
      get().pollJobStatus(res.job_id);
    } catch (error) {
      console.error('Failed to trigger fetch:', error);
      set({ fetchStatus: 'failed' });
    }
  },

  pollJobStatus: async (jobId) => {
    const interval = setInterval(async () => {
      try {
        const status = await newsApi.getJobStatus(jobId);
        set({
          fetchProgress: {
            total: status.total_fetched,
            deduped: status.after_dedup,
            enriched: status.after_enrich,
          },
        });

        if (status.status === 'completed' || status.status === 'failed') {
          clearInterval(interval);
          set({ fetchStatus: status.status });
          if (status.status === 'completed') {
            await get().loadArticles();
          }
        }
      } catch (error) {
        console.error('Failed to poll job status:', error);
        clearInterval(interval);
        set({ fetchStatus: 'failed' });
      }
    }, 2000);
  },

  loadArticles: async () => {
    const { filters, currentPage } = get();
    try {
      const res = await newsApi.getArticles({
        ...filters,
        page: currentPage,
      });
      set({ articles: res.items, totalCount: res.total });
    } catch (error) {
      console.error('Failed to load articles:', error);
    }
  },

  updateArticle: async (id, patch) => {
    try {
      await newsApi.patchArticle(id, patch);
      // Optimistic update
      set((state) => ({
        articles: state.articles.map((a) => (a.id === id ? { ...a, ...patch } : a)),
        archiveResults: state.archiveResults.map((a) => (a.id === id ? { ...a, ...patch } : a)),
      }));
    } catch (error) {
      console.error('Failed to update article:', error);
      await get().loadArticles(); // Revert on failure
    }
  },

  batchAction: async (action) => {
    const { selectedIds } = get();
    if (selectedIds.size === 0) return;

    try {
      await newsApi.batchArticles(Array.from(selectedIds), action);
      set({ selectedIds: new Set() });
      await get().loadArticles();
    } catch (error) {
      console.error(`Failed to batch ${action}:`, error);
    }
  },

  toggleSelect: (id) => {
    set((state) => {
      const newSelected = new Set(state.selectedIds);
      if (newSelected.has(id)) {
        newSelected.delete(id);
      } else {
        newSelected.add(id);
      }
      return { selectedIds: newSelected };
    });
  },

  selectAll: () => {
    set((state) => ({
      selectedIds: new Set(state.articles.map((a) => a.id)),
    }));
  },

  clearSelection: () => {
    set({ selectedIds: new Set() });
  },

  setFilter: (key, value) => {
    set((state) => ({
      filters: { ...state.filters, [key]: value },
      currentPage: 1, // Reset to page 1 on filter change
    }));
    get().loadArticles();
  },

  loadArchiveStats: async () => {
    try {
      const stats = await newsApi.getArchiveStats();
      set({ archiveStats: stats });
    } catch (error) {
      console.error('Failed to load archive stats:', error);
    }
  },

  loadAvailableTags: async () => {
    try {
      const res = await newsApi.getAvailableTags();
      set({ availableTags: res.tags });
    } catch (error) {
      console.error('Failed to load available tags:', error);
    }
  },

  searchArchive: async () => {
    const { archiveFilters, archiveCurrentPage } = get();
    try {
      const res = await newsApi.getArchive({
        ...archiveFilters,
        page: archiveCurrentPage,
      });
      set({ archiveResults: res.items, archiveTotalCount: res.total });
    } catch (error) {
      console.error('Failed to search archive:', error);
    }
  },

  setArchiveFilter: (key, value) => {
    set((state) => ({
      archiveFilters: { ...state.archiveFilters, [key]: value },
      archiveCurrentPage: 1,
    }));
    get().searchArchive();
  },

  addTagFilter: (tag) => {
    set((state) => {
      if (state.archiveFilters.tags.includes(tag)) return state;
      return {
        archiveFilters: {
          ...state.archiveFilters,
          tags: [...state.archiveFilters.tags, tag],
        },
        archiveCurrentPage: 1,
      };
    });
    get().searchArchive();
  },

  removeTagFilter: (tag) => {
    set((state) => ({
      archiveFilters: {
        ...state.archiveFilters,
        tags: state.archiveFilters.tags.filter((t) => t !== tag),
      },
      archiveCurrentPage: 1,
    }));
    get().searchArchive();
  },

  resetArchiveFilters: () => {
    set({
      archiveFilters: {
        tags: [],
        source: 'all',
        language: 'all',
        dateFrom: null,
        dateTo: null,
        search: '',
        isStarred: null,
        sortBy: 'archived_at',
        sortOrder: 'desc',
      },
      archiveCurrentPage: 1,
    });
    get().searchArchive();
  },

  retryKbPush: async (articleIds) => {
    try {
      await newsApi.retryKbPush(articleIds);
      await get().searchArchive();
      await get().loadArchiveStats();
    } catch (error) {
      console.error('Failed to retry KB push:', error);
    }
  },
}));
