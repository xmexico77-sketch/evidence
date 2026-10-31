/**
 * 运行时 API 代理。
 *
 * 为什么不用 next.config.mjs 的 rewrites：rewrites 的目标地址在**构建时**
 * 就被写进 .next/routes-manifest.json（实测里是 http://127.0.0.1:8000），
 * 运行时再设 API_BASE 完全无效。
 *
 * 后果很严重：docker-compose 里前端容器的 API_BASE=http://api:8000 不会生效，
 * 容器内会去连自己的 127.0.0.1:8000 → 全站接口不可用。
 *
 * 改成一个 Route Handler，每次请求读 process.env.API_BASE，开发与容器都正确。
 */

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

function apiBase(): string {
  return process.env.API_BASE ?? "http://127.0.0.1:8000";
}

async function proxy(
  req: Request,
  ctx: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await ctx.params;
  const incoming = new URL(req.url);
  const target = `${apiBase()}/api/${path.join("/")}${incoming.search}`;

  const headers = new Headers(req.headers);
  headers.delete("host");
  headers.delete("connection");

  const init: RequestInit & { duplex?: "half" } = {
    method: req.method,
    headers,
    redirect: "manual",
  };

  // GET/HEAD 不带 body；其余请求流式转发（上传 PDF、CSV 都走这里）
  if (req.method !== "GET" && req.method !== "HEAD" && req.body) {
    init.body = req.body;
    init.duplex = "half";
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, init);
  } catch (e) {
    return new Response(
      JSON.stringify({
        detail: `后端不可达（${apiBase()}）：${e instanceof Error ? e.message : String(e)}`,
      }),
      { status: 502, headers: { "content-type": "application/json; charset=utf-8" } },
    );
  }

  const out = new Headers(upstream.headers);
  // 这几个头交给运行时重新计算，直接透传会出错
  out.delete("content-encoding");
  out.delete("content-length");
  out.delete("transfer-encoding");

  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export {
  proxy as GET,
  proxy as POST,
  proxy as PUT,
  proxy as PATCH,
  proxy as DELETE,
  proxy as HEAD,
};
