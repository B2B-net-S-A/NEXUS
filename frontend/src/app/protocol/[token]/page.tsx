/**
 * Potwierdzenie odbioru sprzętu — `/protocol/{token}` (decyzja D8).
 *
 * Osoba widzi treść swojego protokołu (ten sam tekst co w pliku), wpisuje imię
 * i nazwisko i potwierdza odbiór. Podpis zatwierdza potem recepcja. Zły,
 * zużyty i wygasły link dają ten sam komunikat (serwer nie rozróżnia przyczyn).
 */
import { PackageCheck } from "lucide-react";

import { PublicLinkUnavailable } from "@/components/public/PublicLinkUnavailable";
import { publicLinkFailure } from "@/lib/public-link-state";
import { forwardedClientHeaders } from "@/lib/server-forwarded";

import { ProtocolSignForm, type PublicProtocol } from "./ProtocolSignForm";

interface PageProps {
  params: Promise<{ token: string }>;
}

function apiBase(): string {
  return process.env.INTERNAL_API_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
}

async function fetchProtocol(
  token: string,
): Promise<{ protocol: PublicProtocol } | { status: number | null }> {
  try {
    const res = await fetch(
      `${apiBase()}/api/public/equipment-protocols/${encodeURIComponent(token)}`,
      { cache: "no-store", headers: await forwardedClientHeaders() },
    );
    if (!res.ok) return { status: res.status };
    return { protocol: (await res.json()) as PublicProtocol };
  } catch {
    return { status: null };
  }
}

export default async function ProtocolPage({ params }: PageProps) {
  const { token } = await params;
  const result = await fetchProtocol(token);
  if (!("protocol" in result)) {
    return <PublicLinkUnavailable failure={publicLinkFailure(result.status)} />;
  }
  return (
    <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
      <div className="mb-1 flex items-center gap-3">
        <PackageCheck className="h-7 w-7 text-primary" aria-hidden />
        <h1 className="text-2xl font-semibold">Potwierdzenie odbioru sprzętu</h1>
      </div>
      <p className="mb-6 text-muted-foreground">
        Protokół {result.protocol.number} · {result.protocol.holder_name}
      </p>
      <ProtocolSignForm token={token} protocol={result.protocol} />
    </div>
  );
}
