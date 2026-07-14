import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const NO_STORE_HEADERS = {
  "Cache-Control": "no-store",
  "Content-Type": "application/json; charset=utf-8",
};

function unavailable(): NextResponse {
  return NextResponse.json(
    {
      status: "unhealthy",
      version: process.env.NEXT_PUBLIC_GIT_SHA || "unknown",
      deployedAt: "unknown",
      checks: { database: { status: "unhealthy" } },
    },
    { status: 503, headers: NO_STORE_HEADERS },
  );
}

/**
 * Same-origin readiness facade for release automation and Cloudflare Access.
 * The backend remains authoritative; this route preserves its status and safe
 * JSON contract while allowing staging UI E2E and readiness to share one
 * application origin, as required by the locked release workflow.
 */
export async function GET(): Promise<NextResponse> {
  const backendBase = (
    process.env.INTERNAL_API_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    ""
  ).replace(/\/$/, "");
  if (!backendBase) return unavailable();

  try {
    const response = await fetch(`${backendBase}/api/health`, {
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    const payload: unknown = await response.json();
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      return unavailable();
    }
    return NextResponse.json(payload, {
      status: response.status,
      headers: NO_STORE_HEADERS,
    });
  } catch {
    return unavailable();
  }
}
