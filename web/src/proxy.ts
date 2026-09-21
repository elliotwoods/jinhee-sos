import { NextResponse, type NextRequest } from "next/server";
import { password, SESSION_COOKIE, sessionValue } from "@/lib/http";

/**
 * Browser pages need the session cookie set by /login. The desktop API (/api/inventory*)
 * checks `Authorization: Bearer <password>` itself; /login and /api/session are public.
 */
export async function proxy(req: NextRequest): Promise<NextResponse> {
  const signedIn = password() !== "" && req.cookies.get(SESSION_COOKIE)?.value === (await sessionValue());
  if (signedIn) return NextResponse.next();
  return NextResponse.redirect(new URL("/login", req.url));
}

export const config = { matcher: ["/"] };
