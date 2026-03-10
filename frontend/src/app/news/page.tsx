'use client';

import React, { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useNewsStore } from '@/stores/newsStore';
import { FetchButton } from './components/FetchButton';
import { FilterBar } from './components/FilterBar';
import { ArticleList } from './components/ArticleList';
import { BatchActions } from './components/BatchActions';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Newspaper, Archive } from 'lucide-react';

export default function NewsPage() {
  const router = useRouter();
  const { loadArticles } = useNewsStore();

  useEffect(() => {
    loadArticles();
  }, [loadArticles]);

  return (
    <div className="min-h-screen bg-[#F5F5F7] pb-20">
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-8">
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 mb-8">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 mb-2 flex items-center gap-2">
              <Newspaper className="w-8 h-8 text-blue-600" />
              资讯中心
            </h1>
            <p className="text-gray-500">聚合全网 AI 资讯，AI 辅助审阅入库</p>
          </div>
          
          <div className="flex items-center gap-4">
            <Tabs value="pending" className="w-[200px]">
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="pending">待审阅</TabsTrigger>
                <TabsTrigger value="archive" onClick={() => router.push('/news/archive')}>
                  <div className="flex items-center gap-1">
                    <Archive className="w-4 h-4" /> 归档
                  </div>
                </TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
        </div>

        <div className="flex flex-col gap-6">
          <div className="flex flex-col md:flex-row justify-between gap-4">
            <FetchButton />
            <FilterBar />
          </div>

          <ArticleList />
        </div>
      </main>

      <BatchActions />
    </div>
  );
}
