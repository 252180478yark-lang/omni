import React from 'react';
import { Button } from '@/components/ui/button';
import { RefreshCw, Loader2 } from 'lucide-react';
import { useNewsStore } from '@/stores/newsStore';

export function FetchButton() {
  const { fetchStatus, fetchProgress, triggerFetch } = useNewsStore();

  const handleFetch = () => {
    if (fetchStatus !== 'fetching' && fetchStatus !== 'enriching') {
      triggerFetch();
    }
  };

  const isLoading = fetchStatus === 'fetching' || fetchStatus === 'enriching';

  return (
    <div className="flex items-center gap-4">
      <Button 
        onClick={handleFetch} 
        disabled={isLoading}
        className="bg-blue-600 hover:bg-blue-700 text-white"
      >
        {isLoading ? (
          <Loader2 className="w-4 h-4 mr-2 animate-spin" />
        ) : (
          <RefreshCw className="w-4 h-4 mr-2" />
        )}
        {isLoading ? '拉取中...' : '拉取最新资讯'}
      </Button>

      {isLoading && (
        <div className="text-sm text-gray-500 flex items-center gap-2">
          <span>已抓取: {fetchProgress.total}</span>
          <span>| 去重后: {fetchProgress.deduped}</span>
          <span>| AI处理: {fetchProgress.enriched}</span>
        </div>
      )}

      {fetchStatus === 'completed' && (
        <div className="text-sm text-green-600">
          拉取完成！新增 {fetchProgress.enriched} 条资讯。
        </div>
      )}

      {fetchStatus === 'failed' && (
        <div className="text-sm text-red-600">
          拉取失败，请重试。
        </div>
      )}
    </div>
  );
}
