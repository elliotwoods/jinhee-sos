import { NextResponse, type NextRequest } from "next/server";
import { passwordMatches, SESSION_COOKIE, sessionValue } from "@/lib/http";

const YEAR = 365 * 24 * 60 * 60;

/** Form POST from /login (sign in) or the header's Sign out button (`action=logout`). */
export async function POST(req: NextRequest) {
  const form = await req.formData();
  if (form.get("action") === "logout") {
    const res = NextResponse.redirect(new URL("/login", req.url), 303);
    res.cookies.delete(SESSION_COOKIE);
    return res;
  }
  if (!passwordMatches(String(form.get("password") ?? ""))) {
    return NextResponse.redirect(new URL("/login?error=1", req.url), 303);
  }
  const res = NextResponse.redirect(new URL("/", req.url), 303);
  res.cookies.set(SESSION_COOKIE, await sessionValue(), {
    httpOnly: true, sameSite: "lax", secure: req.nextUrl.protocol === "https:", maxAge: YEAR, path: "/",
  });
  return res;
}
