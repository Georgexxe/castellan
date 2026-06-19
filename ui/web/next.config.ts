import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  // Pin the workspace root to this app (a stray lockfile in the home dir otherwise
  // makes Next infer the wrong root).
  turbopack: {
    root: path.resolve(__dirname),
  },
};

export default nextConfig;
