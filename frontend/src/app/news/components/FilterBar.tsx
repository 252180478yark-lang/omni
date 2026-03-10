import React, { useEffect, useState } from 'react';
import { useNewsStore } from '@/stores/newsStore';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Search } from 'lucide-react';

export function FilterBar() {
  const { filters, setFilter } = useNewsStore();
  const [searchValue, setSearchValue] = useState(filters.search);

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => {
      if (searchValue !== filters.search) {
        setFilter('search', searchValue);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [searchValue, filters.search, setFilter]);

  return (
    <div className="flex flex-wrap items-center gap-4 bg-white p-4 rounded-xl border border-gray-200 shadow-sm">
      <div className="relative flex-1 min-w-[200px]">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
        <Input 
          placeholder="搜索标题或摘要..." 
          value={searchValue}
          onChange={(e) => setSearchValue(e.target.value)}
          className="pl-9"
        />
      </div>

      <Select value={filters.source} onValueChange={(v) => setFilter('source', v)}>
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

      <Select value={filters.language} onValueChange={(v) => setFilter('language', v)}>
        <SelectTrigger className="w-[120px]">
          <SelectValue placeholder="语言" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">全部语言</SelectItem>
          <SelectItem value="zh">中文</SelectItem>
          <SelectItem value="en">English</SelectItem>
        </SelectContent>
      </Select>

      <Select value={filters.sortOrder} onValueChange={(v) => setFilter('sortOrder', v)}>
        <SelectTrigger className="w-[120px]">
          <SelectValue placeholder="顺序" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="desc">降序</SelectItem>
          <SelectItem value="asc">升序</SelectItem>
        </SelectContent>
      </Select>

      <Select value={filters.sortBy} onValueChange={(v) => setFilter('sortBy', v)}>
        <SelectTrigger className="w-[140px]">
          <SelectValue placeholder="排序" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="fetched_at">按拉取时间</SelectItem>
          <SelectItem value="ai_relevance_score">按相关度</SelectItem>
          <SelectItem value="published_at">按发布时间</SelectItem>
        </SelectContent>
      </Select>
    </div>
  );
}
