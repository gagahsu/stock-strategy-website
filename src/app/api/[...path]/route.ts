import { NextRequest, NextResponse } from "next/server";
export const dynamic = "force-dynamic";
async function handle(
  req: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  const base = process.env.API_BASE_URL || "http://127.0.0.1:8000";
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (process.env.API_TOKEN)
    headers.Authorization = `Bearer ${process.env.API_TOKEN}`;
  if (req.headers.get("origin")) headers.Origin = req.headers.get("origin")!;
  try {
    const response = await fetch(
      `${base}/api/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`,
      {
        method: req.method,
        headers,
        body: ["GET", "HEAD"].includes(req.method)
          ? undefined
          : await req.text(),
        cache: "no-store",
        signal: AbortSignal.timeout(120000),
      },
    );
    return new NextResponse(await response.text(), {
      status: response.status,
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return NextResponse.json(
      { detail: "資料服務無法連線，請確認後端已啟動。" },
      { status: 503 },
    );
  }
}
export { handle as GET, handle as POST, handle as PUT, handle as DELETE };
