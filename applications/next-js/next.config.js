/** @type {import('next').NextConfig} */
module.exports = {
  eslint: {
    // Disabling on production builds because we're running checks on PRs via GitHub Actions.
    ignoreDuringBuilds: true
  },
  output: "standalone",
  assetPrefix: "/unicorn",
  basePath: '/unicorn',
};
