/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 注意：不要在这里用 rewrites 代理 /api。
  // rewrites 的目标地址会在 **构建时** 写进 .next/routes-manifest.json，
  // 之后设 API_BASE 环境变量完全无效——容器里前端会去连自己的
  // 127.0.0.1:8000，导致整站接口不可用（这是实测发现的部署级缺陷）。
  // 代理改由 app/api/[...path]/route.ts 在运行时读取 API_BASE 处理。
};

export default nextConfig;
