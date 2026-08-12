/** @type {import('next').NextConfig} */
const nextConfig = {
  // Required for the multi-stage Dockerfile: standalone mode traces and
  // bundles only the node_modules a production run actually needs into
  // .next/standalone, instead of shipping the whole node_modules tree.
  output: "standalone",
};

export default nextConfig;
