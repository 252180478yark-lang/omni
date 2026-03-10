import React, { useState } from 'react';
import { Button } from '@/components/ui/button';
import { RefreshCw, Loader2, Settings2 } from 'lucide-react';
import { useNewsStore } from '@/stores/newsStore';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

export function FetchButton() {
  const { fetchStatus, fetchProgress, triggerFetch } = useNewsStore();
  const [sources, setSources] = useState<string[]>(['serper', 'bocha', 'tianapi']);
  const [keywords, setKeywords] = useState('');
  const [freshness, setFreshness] = useState('oneDay');

  const handleFetch = () => {
    if (fetchStatus !== 'fetching' && fetchStatus !== 'enriching') {
      const keywordsArray = keywords.trim() ? keywords.split(',').map(k => k.trim()) : null;
      triggerFetch({
        sources: sources.length > 0 ? sources : undefined,
        keywords_override: keywordsArray,
        freshness_override: freshness === 'oneDay' ? null : freshness,
      });
    }
  };

  const toggleSource = (source: string) => {
    setSources(prev => 
      prev.includes(source) 
        ? prev.filter(s => s !== source)
        : [...prev, source]
    );
  };

  const isLoading = fetchStatus === 'fetching' || fetchStatus === 'enriching';

  return (
    <div className="flex items-center gap-4">
      <div className="flex items-center">
        <Button 
          onClick={handleFetch} 
          disabled={isLoading}
          className="bg-blue-600 hover:bg-blue-700 text-white rounded-r-none border-r border-blue-700"
        >
          {isLoading ? (
            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
          ) : (
            <RefreshCw className="w-4 h-4 mr-2" />
          )}
          {isLoading ? (fetchStatus === 'enriching' ? 'AI处理中...' : '拉取中...') : '拉取最新资讯'}
        </Button>
        <Popover>
          <PopoverTrigger
            className="inline-flex h-10 items-center justify-center rounded-r-md bg-blue-600 px-2 text-white transition-colors hover:bg-blue-700 disabled:pointer-events-none disabled:opacity-50"
            disabled={isLoading}
            aria-label="拉取选项配置"
          >
            <Settings2 className="h-4 w-4" />
          </PopoverTrigger>
          <PopoverContent className="w-80 p-4" align="start">
            <div className="space-y-4">
              <h4 className="font-medium text-sm border-b pb-2">拉取选项配置</h4>
              
              <div className="space-y-2">
                <label className="text-xs font-semibold text-gray-500">启用的数据源</label>
                <div className="flex flex-col gap-2">
                  <label className="flex items-center gap-2 text-sm cursor-pointer">
                    <Checkbox checked={sources.includes('serper')} onCheckedChange={() => toggleSource('serper')} />
                    Serper (英文新闻)
                  </label>
                  <label className="flex items-center gap-2 text-sm cursor-pointer">
                    <Checkbox checked={sources.includes('bocha')} onCheckedChange={() => toggleSource('bocha')} />
                    Bocha (中文全网)
                  </label>
                  <label className="flex items-center gap-2 text-sm cursor-pointer">
                    <Checkbox checked={sources.includes('tianapi')} onCheckedChange={() => toggleSource('tianapi')} />
                    Tianapi (科技资讯)
                  </label>
                </div>
              </div>

              <div className="space-y-2">
                <label className="text-xs font-semibold text-gray-500">关键词覆盖 (逗号分隔)</label>
                <Input 
                  placeholder="留空则使用默认配置..." 
                  value={keywords}
                  onChange={e => setKeywords(e.target.value)}
                  className="h-8 text-sm"
                />
              </div>

              <div className="space-y-2">
                <label className="text-xs font-semibold text-gray-500">时间范围</label>
                <Select value={freshness} onValueChange={(value) => setFreshness(value ?? 'oneDay')}>
                  <SelectTrigger className="h-8 text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="oneDay">最近 24 小时</SelectItem>
                    <SelectItem value="oneWeek">最近 1 周</SelectItem>
                    <SelectItem value="oneMonth">最近 1 个月</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </PopoverContent>
        </Popover>
      </div>

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
        <div className="text-sm text-red-600 flex items-center gap-2">
          <span>拉取失败，请重试。</span>
          <Button variant="outline" size="sm" onClick={handleFetch}>
            重试
          </Button>
        </div>
      )}
    </div>
  );
}
