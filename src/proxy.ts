import { NextRequest, NextResponse } from "next/server";
import { timingSafeEqual } from "node:crypto";
export function proxy(req: NextRequest) {
  const password = process.env.APP_PASSWORD;
  if (!password) {
    const host = req.nextUrl.hostname;
    if (!["localhost", "127.0.0.1", "::1"].includes(host))
      return new NextResponse("請先設定 APP_PASSWORD 再開放遠端使用。", {
        status: 403,
      });
    return NextResponse.next();
  }
  const auth = req.headers.get("authorization") || "";
  let valid = false;
  if (auth.startsWith("Basic ")) {
    const decoded = Buffer.from(auth.slice(6), "base64").toString();
    const sep = decoded.indexOf(":");
    const user = decoded.slice(0, sep);
    const pass = Buffer.from(decoded.slice(sep + 1));
    const expected = Buffer.from(password);
    valid =
      user === "owner" &&
      pass.length === expected.length &&
      timingSafeEqual(pass, expected);
  }
  return valid
    ? NextResponse.next()
    : new NextResponse("請使用個人帳號登入。", {
        status: 401,
        headers: {
          "WWW-Authenticate": 'Basic realm="Stock research", charset="UTF-8"',
        },
      });
}
export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
