import React from 'react';
import { useNewsStore } from '@/stores/newsStore';
import { Card, CardContent } from '@/components/ui/card';
import { Database, TrendingUp, Tags, CheckCircle2, Clock } from 'lucide-react';

export function ArchiveStats() {
  const { archiveStats } = useNewsStore();

  if (!archiveStats) return null;

  const statCards = [
    { 
      title: "总归档数", 
      value: archiveStats.total_archived, 
      subtitle: `近7天新增 ${archiveStats.recent_7d_count} 篇`,
      icon: Database, 
      color: "text-blue-500", 
      bg: "bg-blue-50" 
    },
    { 
      title: "知识库同步", 
      value: archiveStats.kb_synced_count, 
      subtitle: archiveStats.kb_pending_count > 0 ? `${archiveStats.kb_pending_count} 篇待同步` : '全部同步完成',
      icon: archiveStats.kb_pending_count > 0 ? Clock : CheckCircle2, 
      color: archiveStats.kb_pending_count > 0 ? "text-yellow-500" : "text-green-500", 
      bg: archiveStats.kb_pending_count > 0 ? "bg-yellow-50" : "bg-green-50" 
    },
    { 
      title: "来源分布", 
      value: Object.keys(archiveStats.by_source).length, 
      subtitle: `Serper: ${archiveStats.by_source.serper || 0}, Bocha: ${archiveStats.by_source.bocha || 0}`,
      icon: TrendingUp, 
      color: "text-purple-500", 
      bg: "bg-purple-50" 
    },
    { 
      title: "热门标签", 
      value: archiveStats.top_tags.length > 0 ? archiveStats.top_tags[0].tag : '-', 
      subtitle: `共 ${archiveStats.top_tags.length} 个活跃标签`,
      icon: Tags, 
      color: "text-orange-500", 
      bg: "bg-orange-50" 
    },
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      {statCards.map((stat, i) => (
        <Card key={i} className="border-none shadow-sm hover:shadow-md transition-shadow">
          <CardContent className="p-5">
            <div className="flex items-center justify-between mb-2">
              <div className={`p-2.5 rounded-xl ${stat.bg}`}>
                <stat.icon className={`w-5 h-5 ${stat.color}`} />
              </div>
            </div>
            <div>
              <p className="text-sm font-medium text-gray-500">{stat.title}</p>
              <h3 className="text-2xl font-bold text-gray-900 mt-1">{stat.value}</h3>
              <p className="text-xs text-gray-400 mt-1">{stat.subtitle}</p>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
