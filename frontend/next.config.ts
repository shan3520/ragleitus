import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emits .next/standalone (server.js plus only the node_modules it needs) for the Docker image.
  output: "standalone",
};

export default nextConfig;
