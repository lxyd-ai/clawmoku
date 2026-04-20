/** @type {import('next').NextConfig} */
const API_INTERNAL = process.env.CLAWMOKU_API_INTERNAL || "http://127.0.0.1:9001";

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_INTERNAL}/api/:path*` },
      { source: "/skill.md", destination: `${API_INTERNAL}/skill.md` },
      { source: "/protocol.md", destination: `${API_INTERNAL}/protocol.md` },
      {
        source: "/clawmoku-cred.py",
        destination: `${API_INTERNAL}/clawmoku-cred.py`,
      },
      {
        source: "/matches/:id/claim",
        destination: `${API_INTERNAL}/matches/:id/claim`,
      },
      {
        source: "/matches/:id/claim.txt",
        destination: `${API_INTERNAL}/matches/:id/claim.txt`,
      },
    ];
  },
};

module.exports = nextConfig;
