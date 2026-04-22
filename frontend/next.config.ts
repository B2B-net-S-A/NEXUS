import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  // In production Docker, API calls go through direct fetch (no rewrites needed)
  // Browser calls go to NEXT_PUBLIC_API_URL directly
  // Dev build speed-up: skip lint + type-check during `next build` so docker
  // rebuilds stay fast. CI and IDE still run these.
  eslint: { ignoreDuringBuilds: true },
  typescript: { ignoreBuildErrors: true },
};

export default nextConfig;
