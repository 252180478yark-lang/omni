import React from 'react';
import { useNewsStore } from '@/stores/newsStore';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Database, TrendingUp, Tags, CheckCircle2, Clock } from 'lucide-react';
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts';

export function ArchiveStats() {
  const { archiveStats } = useNewsStore();

  if (!archiveStats) return null;

  const sourceData = Object.entries(archiveStats.by_source)
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value);
  const syncData = [
    { name: '已同步', value: archiveStats.kb_synced_count },
    { name: '待同步', value: archiveStats.kb_pending_count },
  ];
  const sourceColors = ['#3B82F6', '#10B981', '#F59E0B', '#8B5CF6'];
  const syncColors = ['#22C55E', '#F59E0B'];

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
    <div className="space-y-4 mb-6">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
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

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="border-none shadow-sm">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold text-gray-700">来源分布</CardTitle>
          </CardHeader>
          <CardContent className="h-56">
            {sourceData.length === 0 ? (
              <div className="h-full flex items-center justify-center text-sm text-gray-400">暂无来源数据</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={sourceData} dataKey="value" nameKey="name" outerRadius={80} innerRadius={45}>
                    {sourceData.map((_, idx) => (
                      <Cell key={idx} fill={sourceColors[idx % sourceColors.length]} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card className="border-none shadow-sm">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold text-gray-700">知识库同步状态</CardTitle>
          </CardHeader>
          <CardContent className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={syncData} dataKey="value" nameKey="name" outerRadius={80} innerRadius={45}>
                  {syncData.map((_, idx) => (
                    <Cell key={idx} fill={syncColors[idx]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card className="border-none shadow-sm">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold text-gray-700">Top Tags</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {archiveStats.top_tags.length === 0 && (
                <div className="text-sm text-gray-400">暂无标签数据</div>
              )}
              {archiveStats.top_tags.slice(0, 12).map((item) => (
                <Badge key={item.tag} variant="secondary" className="bg-slate-100 text-slate-700">
                  {item.tag} ({item.count})
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
