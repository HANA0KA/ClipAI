import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { rejectReason } from "@/lib/local-guard";

/** Barrera de la web local: rechaza Host/Origin ajenos (ver lib/local-guard.ts). */
export function proxy(request: NextRequest) {
  const reason = rejectReason({
    method: request.method,
    pathname: request.nextUrl.pathname,
    headers: request.headers,
  });
  if (reason) return NextResponse.json({ error: reason }, { status: 403 });
  return NextResponse.next();
}

export const config = {
  // Todo menos los archivos estáticos de la propia compilación.
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
