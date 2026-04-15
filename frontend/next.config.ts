import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  // In production Docker, API calls go through direct fetch (no rewrites needed)
  // Browser calls go to NEXT_PUBLIC_API_URL directly
};

export default nextConfig;
