import type { NextConfig } from "next";

// The browser always calls /api/* on the frontend's own origin; Next.js forwards it
// to the FastAPI backend inside the Docker network. No CORS needed.
const backendUrl = process.env.BACKEND_URL ?? "http://backend:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  // Gzip would buffer Server-Sent Events (the streamed AI replies) until the turn ends.
  // Leave compression to a reverse proxy that can exclude text/event-stream.
  compress: false,
  // Guided-assessment turns call the AI with tools and can take longer than the default 30s.
  experimental: { proxyTimeout: 180_000 },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendUrl}/:path*` }];
  },
};

export default nextConfig;
