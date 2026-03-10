import React from 'react';
import { Article } from '@/lib/api/news';
import { useNewsStore } from '@/stores/newsStore';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { Button } from '@/components/ui/button';
import { Star, X, ExternalLink, CheckCircle } from 'lucide-react';

interface ArticleCardProps {
  article: Article;
  readonly?: boolean;
}

export function ArticleCard({ article, readonly = false }: ArticleCardProps) {
  const { selectedIds, toggleSelect, updateArticle, retryKbPush } = useNewsStore();
  const isSelected = selectedIds.has(article.id);

  const sourceColors = {
    serper: 'bg-blue-100 text-blue-800 border-blue-200',
    bocha: 'bg-green-100 text-green-800 border-green-200',
    tianapi: 'bg-orange-100 text-orange-800 border-orange-200',
  };

  const getRelevanceColor = (score: number) => {
    if (score >= 0.8) return 'bg-green-500';
    if (score >= 0.5) return 'bg-yellow-500';
    return 'bg-red-500';
  };

  return (
    <Card className={`relative transition-all duration-200 ${isSelected ? 'ring-2 ring-blue-500 bg-blue-50/30' : 'hover:shadow-md'}`}>
      <CardContent className="p-5">
        <div className="flex gap-4">
          {!readonly && (
            <div className="pt-1">
              <Checkbox 
                checked={isSelected} 
                onCheckedChange={() => toggleSelect(article.id)} 
              />
            </div>
          )}
          
          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between gap-4 mb-2">
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <Badge variant="outline" className={sourceColors[article.source]}>
                    {article.source_name || article.source}
                  </Badge>
                  <Badge variant="outline" className="text-gray-500">
                    {article.language === 'zh' ? '🇨🇳 ZH' : '🌐 EN'}
                  </Badge>
                  {article.status === 'archived' && (
                    <Badge variant="secondary" className="bg-purple-100 text-purple-800">
                      已归档
                    </Badge>
                  )}
                  {article.kb_doc_id && (
                    <Badge variant="secondary" className="bg-green-100 text-green-800 flex items-center gap-1">
                      <CheckCircle className="w-3 h-3" /> 已入库
                    </Badge>
                  )}
                  {article.status === 'archived' && !article.kb_doc_id && (
                    <Badge variant="secondary" className="bg-yellow-100 text-yellow-800">
                      待向量化
                    </Badge>
                  )}
                </div>
                <a 
                  href={article.url} 
                  target="_blank" 
                  rel="noopener noreferrer"
                  className="text-lg font-semibold text-gray-900 hover:text-blue-600 line-clamp-2 flex items-center gap-2 group"
                >
                  {article.title}
                  <ExternalLink className="w-4 h-4 opacity-0 group-hover:opacity-100 transition-opacity" />
                </a>
              </div>
              
              {!readonly && (
                <div className="flex items-center gap-2 shrink-0">
                  <Button 
                    variant="ghost" 
                    size="icon" 
                    onClick={() => updateArticle(article.id, { is_starred: !article.is_starred })}
                    className={article.is_starred ? 'text-yellow-500 hover:text-yellow-600' : 'text-gray-400 hover:text-yellow-500'}
                  >
                    <Star className="w-5 h-5" fill={article.is_starred ? 'currentColor' : 'none'} />
                  </Button>
                  <Button 
                    variant="ghost" 
                    size="icon"
                    onClick={() => updateArticle(article.id, { status: 'dismissed' })}
                    className="text-gray-400 hover:text-red-500"
                  >
                    <X className="w-5 h-5" />
                  </Button>
                </div>
              )}
              {readonly && (
                <div className="flex items-center gap-2 shrink-0">
                  {article.is_starred && <Star className="w-5 h-5 text-yellow-500" fill="currentColor" />}
                  {article.status === 'archived' && !article.kb_doc_id && (
                    <Button variant="outline" size="sm" onClick={() => retryKbPush([article.id])}>
                      重试推送
                    </Button>
                  )}
                </div>
              )}
            </div>

            <p className="text-gray-600 text-sm mb-4 line-clamp-3">
              {article.ai_summary || article.raw_snippet}
            </p>

            <div className="flex items-center justify-between mt-auto">
              <div className="flex flex-wrap gap-2">
                {article.ai_tags.map((tag, i) => (
                  <Badge key={i} variant="secondary" className="bg-gray-100 text-gray-700 hover:bg-gray-200">
                    {tag}
                  </Badge>
                ))}
              </div>
              
              <div className="flex items-center gap-3 shrink-0 ml-4">
                <div className="flex flex-col items-end">
                  <span className="text-xs text-gray-500 mb-1">相关度: {(article.ai_relevance_score * 100).toFixed(0)}%</span>
                  <div className="w-24 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                    <div 
                      className={`h-full ${getRelevanceColor(article.ai_relevance_score)}`}
                      style={{ width: `${article.ai_relevance_score * 100}%` }}
                    />
                  </div>
                </div>
                <span className="text-xs text-gray-400">
                  {new Date(article.fetched_at).toLocaleString('zh-CN', {
                    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
                  })}
                </span>
              </div>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
