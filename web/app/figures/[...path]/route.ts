/**
 * 图表静态文件代理。
 *
 * 后端用 StaticFiles 把生成的 PNG/SVG 挂在 /figures 下，
 * 但前端只代理了 /api——于是页面上的 <img src="/figures/xxx.png"> 全是裂图。
 * （本会话实测：图表文字、图注、选型理由都正常，只有图不显示。）
 *
 * 与 /api 代理同理：运行时读 API_BASE，不能靠构建期 rewrite。
 */

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

function apiBase(): string {
  return process.env.API_BASE ?? "http://127.0.0.1:8000";
}

async function proxy(
  _req: Request,
  ctx: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await ctx.params;
  const target = `${apiBase()}/figures/${path.join("/")}`;
  let upstream: Response;
  try {
    upstream = await fetch(target, { redirect: "manual" });
  } catch (e) {
    return new Response(
      `图表服务不可达（${apiBase()}）：${e instanceof Error ? e.message : String(e)}`,
      { status: 502, headers: { "content-type": "text/plain; charset=utf-8" } },
    );
  }
  const out = new Headers(upstream.headers);
  out.delete("content-encoding");
  out.delete("content-length");
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export { proxy as GET, proxy as HEAD };
