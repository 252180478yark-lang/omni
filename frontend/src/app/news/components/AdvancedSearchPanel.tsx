import React, { useEffect, useState } from 'react';
import { useNewsStore } from '@/stores/newsStore';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Search, RotateCcw, Lightbulb } from 'lucide-react';
import { TagSelector } from './TagSelector';
import Link from 'next/link';

export function AdvancedSearchPanel() {
  const { archiveFilters, setArchiveFilter, resetArchiveFilters } = useNewsStore();
  const [searchValue, setSearchValue] = useState(archiveFilters.search);

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => {
      if (searchValue !== archiveFilters.search) {
        setArchiveFilter('search', searchValue);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [searchValue, archiveFilters.search, setArchiveFilter]);

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden mb-6">
      <div className="p-5 space-y-4">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <Input 
              type="date" 
              className="w-[150px]" 
              value={archiveFilters.dateFrom || ''}
              onChange={(e) => setArchiveFilter('dateFrom', e.target.value || null)}
            />
            <span className="text-gray-400">至</span>
            <Input 
              type="date" 
              className="w-[150px]"
              value={archiveFilters.dateTo || ''}
              onChange={(e) => setArchiveFilter('dateTo', e.target.value || null)}
            />
          </div>

          <Select value={archiveFilters.source} onValueChange={(v) => setArchiveFilter('source', v)}>
            <SelectTrigger className="w-[140px]">
              <SelectValue placeholder="来源" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部来源</SelectItem>
              <SelectItem value="serper">Serper (英文)</SelectItem>
              <SelectItem value="bocha">Bocha (中文)</SelectItem>
              <SelectItem value="tianapi">Tianapi (科技)</SelectItem>
            </SelectContent>
          </Select>

          <Select value={archiveFilters.language} onValueChange={(v) => setArchiveFilter('language', v)}>
            <SelectTrigger className="w-[120px]">
              <SelectValue placeholder="语言" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部语言</SelectItem>
              <SelectItem value="zh">中文</SelectItem>
              <SelectItem value="en">English</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-center gap-4">
          <span className="text-sm font-medium text-gray-500 w-16">标签筛选:</span>
          <TagSelector />
        </div>

        <div className="flex flex-wrap items-center gap-4">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <Input 
              placeholder="搜索标题或摘要..." 
              value={searchValue}
              onChange={(e) => setSearchValue(e.target.value)}
              className="pl-9"
            />
          </div>

          <div className="flex items-center space-x-2">
            <Checkbox 
              id="starred" 
              checked={archiveFilters.isStarred === true}
              onCheckedChange={(checked) => setArchiveFilter('isStarred', checked === true ? true : null)}
            />
            <label htmlFor="starred" className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">
              仅星标
            </label>
          </div>

          <Select value={archiveFilters.sortBy} onValueChange={(v) => setArchiveFilter('sortBy', v)}>
            <SelectTrigger className="w-[140px]">
              <SelectValue placeholder="排序" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="archived_at">按归档时间</SelectItem>
              <SelectItem value="published_at">按发布时间</SelectItem>
              <SelectItem value="ai_relevance_score">按相关度</SelectItem>
            </SelectContent>
          </Select>

          <Button variant="ghost" onClick={resetArchiveFilters} className="text-gray-500">
            <RotateCcw className="w-4 h-4 mr-2" />
            重置
          </Button>
        </div>
      </div>
      
      <div className="bg-blue-50/50 px-5 py-3 border-t border-gray-100 flex items-center justify-between">
        <div className="flex items-center text-sm text-blue-800">
          <Lightbulb className="w-4 h-4 mr-2 text-yellow-500" />
          想用自然语言提问？前往 Knowledge 页面使用 AI 检索
        </div>
        <Link href="/knowledge">
          <Button variant="link" size="sm" className="text-blue-600 hover:text-blue-800">
            去提问 →
          </Button>
        </Link>
      </div>
    </div>
  );
}
