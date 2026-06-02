/** @type {import('next').NextConfig} */
const videoAnalysisUrl = process.env.VIDEO_ANALYSIS_SERVICE_URL || 'http://127.0.0.1:8006';
const livestreamAnalysisUrl = process.env.LIVESTREAM_ANALYSIS_SERVICE_URL || 'http://127.0.0.1:8007';
const newsAggregatorUrl = process.env.NEWS_AGGREGATOR_URL || 'http://127.0.0.1:8005';
const knowledgeEngineUrl = process.env.KNOWLEDGE_ENGINE_URL || 'http://127.0.0.1:8002';

const nextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/v1/news/:path*',
        destination: `${newsAggregatorUrl}/api/v1/news/:path*`,
      },
      {
        source: '/api/v1/video-analysis/:path*',
        destination: `${videoAnalysisUrl}/api/v1/video-analysis/:path*`,
      },
      {
        source: '/api/v1/livestream-analysis/:path*',
        destination: `${livestreamAnalysisUrl}/api/v1/livestream-analysis/:path*`,
      },
      // W4-B 14.4 phase D 候选 D：本地资产磁盘存储
      // KE FastAPI 在 /api/v1/knowledge/static/* mount StaticFiles，dev 模式下 Next.js 透传
      {
        source: '/api/v1/knowledge/static/:path*',
        destination: `${knowledgeEngineUrl}/api/v1/knowledge/static/:path*`,
      },
    ];
  },
};

export default nextConfig;
