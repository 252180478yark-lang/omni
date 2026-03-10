import React from 'react';
import { useNewsStore } from '@/stores/newsStore';
import { Button } from '@/components/ui/button';
import { Archive, XCircle, CheckSquare } from 'lucide-react';

export function BatchActions() {
  const { selectedIds, articles, selectAll, clearSelection, batchAction } = useNewsStore();

  if (selectedIds.size === 0) return null;

  const allSelected = selectedIds.size === articles.length && articles.length > 0;

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 animate-in slide-in-from-bottom-10 fade-in duration-300">
      <div className="bg-gray-900 text-white px-6 py-4 rounded-full shadow-2xl flex items-center gap-6">
        <div className="flex items-center gap-3 border-r border-gray-700 pr-6">
          <span className="font-medium">已选 {selectedIds.size} 篇</span>
          <Button 
            variant="ghost" 
            size="sm" 
            className="text-gray-300 hover:text-white hover:bg-gray-800"
            onClick={allSelected ? clearSelection : selectAll}
          >
            <CheckSquare className="w-4 h-4 mr-2" />
            {allSelected ? '取消全选' : '全选本页'}
          </Button>
        </div>

        <div className="flex items-center gap-3">
          <Button 
            variant="default" 
            className="bg-blue-600 hover:bg-blue-700 text-white rounded-full px-6"
            onClick={() => batchAction('archive')}
          >
            <Archive className="w-4 h-4 mr-2" />
            确认入库
          </Button>
          <Button 
            variant="ghost" 
            className="text-gray-300 hover:text-red-400 hover:bg-gray-800 rounded-full px-6"
            onClick={() => batchAction('dismiss')}
          >
            <XCircle className="w-4 h-4 mr-2" />
            全部忽略
          </Button>
        </div>
      </div>
    </div>
  );
}
