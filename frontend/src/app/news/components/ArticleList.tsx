import React, { useMemo, useRef, useState } from 'react';
import { useNewsStore } from '@/stores/newsStore';
import { ArticleCard } from './ArticleCard';
import { Button } from '@/components/ui/button';
import { ChevronLeft, ChevronRight, Inbox } from 'lucide-react';

interface ArticleListProps {
  isArchive?: boolean;
}

export function ArticleList({ isArchive = false }: ArticleListProps) {
  const { 
    articles, 
    archiveResults, 
    totalCount, 
    archiveTotalCount,
    currentPage,
    archiveCurrentPage,
    pageSize,
    archivePageSize,
    setCurrentPage,
    setArchiveCurrentPage
  } = useNewsStore();
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [scrollTop, setScrollTop] = useState(0);

  const currentArticles = isArchive ? archiveResults : articles;
  const total = isArchive ? archiveTotalCount : totalCount;
  const page = isArchive ? archiveCurrentPage : currentPage;
  const activePageSize = isArchive ? archivePageSize : pageSize;
  const totalPages = Math.ceil(total / activePageSize);
  const shouldVirtualize = currentArticles.length > 50;
  const rowHeight = 240;
  const viewportHeight = 720;
  const overscan = 3;

  const handlePageChange = (newPage: number) => {
    if (isArchive) {
      setArchiveCurrentPage(newPage);
    } else {
      setCurrentPage(newPage);
    }
  };

  const virtualRange = useMemo(() => {
    if (!shouldVirtualize) {
      return {
        start: 0,
        end: currentArticles.length,
      };
    }
    const start = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan);
    const visibleCount = Math.ceil(viewportHeight / rowHeight) + overscan * 2;
    const end = Math.min(currentArticles.length, start + visibleCount);
    return { start, end };
  }, [currentArticles.length, overscan, rowHeight, scrollTop, shouldVirtualize]);

  const visibleArticles = shouldVirtualize
    ? currentArticles.slice(virtualRange.start, virtualRange.end)
    : currentArticles;
  const topSpacerHeight = shouldVirtualize ? virtualRange.start * rowHeight : 0;
  const bottomSpacerHeight = shouldVirtualize
    ? Math.max(0, (currentArticles.length - virtualRange.end) * rowHeight)
    : 0;

  if (currentArticles.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-gray-500">
        <Inbox className="w-16 h-16 mb-4 text-gray-300" />
        <p className="text-lg">暂无数据</p>
        <p className="text-sm">{isArchive ? '尝试调整高级搜索条件' : '尝试调整筛选条件或拉取最新资讯'}</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div
        ref={scrollRef}
        className={shouldVirtualize ? 'max-h-[720px] overflow-y-auto pr-1' : ''}
        onScroll={(event) => {
          if (!shouldVirtualize) return;
          setScrollTop(event.currentTarget.scrollTop);
        }}
      >
        <div className="flex flex-col gap-4">
          {shouldVirtualize && topSpacerHeight > 0 ? (
            <div style={{ height: `${topSpacerHeight}px` }} aria-hidden="true" />
          ) : null}
          {visibleArticles.map((article) => (
            <ArticleCard key={article.id} article={article} readonly={isArchive} />
          ))}
          {shouldVirtualize && bottomSpacerHeight > 0 ? (
            <div style={{ height: `${bottomSpacerHeight}px` }} aria-hidden="true" />
          ) : null}
        </div>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-6 pb-20">
          <div className="text-sm text-gray-500">
            共 {total} 条记录，每页 {activePageSize} 条，第 {page} / {totalPages} 页
          </div>
          <div className="flex gap-2">
            <Button 
              variant="outline" 
              size="sm" 
              onClick={() => handlePageChange(page - 1)}
              disabled={page <= 1}
            >
              <ChevronLeft className="w-4 h-4 mr-1" /> 上一页
            </Button>
            <Button 
              variant="outline" 
              size="sm" 
              onClick={() => handlePageChange(page + 1)}
              disabled={page >= totalPages}
            >
              下一页 <ChevronRight className="w-4 h-4 ml-1" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
