import type { NextConfig } from "next";

const internalApiUrl = process.env.INTERNAL_API_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  devIndicators: {
    position: "bottom-right",
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${internalApiUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
