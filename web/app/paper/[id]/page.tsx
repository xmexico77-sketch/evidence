import Reader from "@/components/Reader";

function parseBox(raw: string | string[] | undefined): number[] | undefined {
  if (typeof raw !== "string") return undefined;
  const parts = raw.split(",").map((v) => Number(v));
  if (parts.length !== 4 || parts.some((v) => !Number.isFinite(v))) return undefined;
  return parts;
}

export default async function PaperPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const pageRaw = typeof sp.page === "string" ? Number(sp.page) : NaN;
  const page = Number.isFinite(pageRaw) && pageRaw > 0 ? Math.floor(pageRaw) : undefined;

  return (
    <Reader paperId={id} initialPage={page} initialBox={parseBox(sp.box)} />
  );
}
