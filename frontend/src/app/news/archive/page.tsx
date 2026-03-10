'use client';

import React, { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useNewsStore } from '@/stores/newsStore';
import { ArchiveStats } from '../components/ArchiveStats';
import { AdvancedSearchPanel } from '../components/AdvancedSearchPanel';
import { ArticleList } from '../components/ArticleList';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Newspaper, Archive } from 'lucide-react';

export default function ArchivePage() {
  const router = useRouter();
  const { loadArchiveStats, loadAvailableTags, searchArchive } = useNewsStore();

  useEffect(() => {
    loadArchiveStats();
    loadAvailableTags();
    searchArchive();
  }, [loadArchiveStats, loadAvailableTags, searchArchive]);

  return (
    <div className="min-h-screen bg-[#F5F5F7] pb-20">
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-8">
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 mb-8">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 mb-2 flex items-center gap-2">
              <Archive className="w-8 h-8 text-purple-600" />
              归档历史
            </h1>
            <p className="text-gray-500">已入库的精选资讯，支持高级搜索与语义检索</p>
          </div>
          
          <div className="flex items-center gap-4">
            <Tabs value="archive" className="w-[200px]">
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="pending" onClick={() => router.push('/news')}>
                  <div className="flex items-center gap-1">
                    <Newspaper className="w-4 h-4" /> 待审阅
                  </div>
                </TabsTrigger>
                <TabsTrigger value="archive">归档</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
        </div>

        <ArchiveStats />
        <AdvancedSearchPanel />
        <ArticleList isArchive={true} />
      </main>
    </div>
  );
}
