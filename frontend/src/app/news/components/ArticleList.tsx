import React from 'react';
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
    setFilter,
    setArchiveFilter
  } = useNewsStore();

  const currentArticles = isArchive ? archiveResults : articles;
  const total = isArchive ? archiveTotalCount : totalCount;
  const page = isArchive ? archiveCurrentPage : currentPage;
  const pageSize = 20; // Fixed for now
  const totalPages = Math.ceil(total / pageSize);

  const handlePageChange = (newPage: number) => {
    if (isArchive) {
      setArchiveFilter('page', newPage);
    } else {
      setFilter('page', newPage);
    }
  };

  if (currentArticles.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-gray-500">
        <Inbox className="w-16 h-16 mb-4 text-gray-300" />
        <p className="text-lg">暂无数据</p>
        <p className="text-sm">尝试调整筛选条件或拉取最新资讯</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-4">
        {currentArticles.map((article) => (
          <ArticleCard key={article.id} article={article} readonly={isArchive} />
        ))}
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-6 pb-20">
          <div className="text-sm text-gray-500">
            共 {total} 条记录，第 {page} / {totalPages} 页
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
