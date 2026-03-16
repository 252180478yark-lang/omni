/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/v1/news/:path*',
        destination: 'http://127.0.0.1:8005/api/v1/news/:path*',
      },
      {
        source: '/api/v1/video-analysis/:path*',
        destination: 'http://127.0.0.1:8006/api/v1/video-analysis/:path*',
      },
      {
        source: '/api/v1/livestream-analysis/:path*',
        destination: 'http://127.0.0.1:8007/api/v1/livestream-analysis/:path*',
      },
    ];
  },
};

export default nextConfig;
