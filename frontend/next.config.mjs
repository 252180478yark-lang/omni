/** @type {import('next').NextConfig} */
const videoAnalysisUrl = process.env.VIDEO_ANALYSIS_SERVICE_URL || 'http://127.0.0.1:8006';
const livestreamAnalysisUrl = process.env.LIVESTREAM_ANALYSIS_SERVICE_URL || 'http://127.0.0.1:8007';
const newsAggregatorUrl = process.env.NEWS_AGGREGATOR_URL || 'http://127.0.0.1:8005';

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
    ];
  },
};

export default nextConfig;
