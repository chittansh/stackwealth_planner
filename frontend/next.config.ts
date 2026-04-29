import type { NextConfig } from 'next';

const config: NextConfig = {
  reactStrictMode: true,
  experimental: {
    typedRoutes: false,
  },
  async rewrites() {
    return [
      {
        source: '/api/backend/:path*',
        destination: `${process.env.BACKEND_URL ?? 'http://localhost:4000'}/api/:path*`,
      },
    ];
  },
};

export default config;
