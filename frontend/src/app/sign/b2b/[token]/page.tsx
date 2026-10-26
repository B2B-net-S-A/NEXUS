/**
 * Podpis umowy B2B w NEXUSIE — strona kontraktora (makieta 5), /sign/b2b/{token}.
 *
 * Kontraktor bez konta pobiera PDF, podpisuje go swoim podpisem kwalifikowanym
 * i wgrywa z powrotem; NEXUS sprawdza podpis na liście zaufanych UE. Strona
 * nie pokazuje kwot. Odmowa i awaria linku mają własne komunikaty.
 */
import { FileSignature } from "lucide-react";

import { PublicLinkUnavailable } from "@/components/public/PublicLinkUnavailable";
import type { PublicSignView } from "@/lib/api/b2bEsign";
import { publicLinkFailure } from "@/lib/public-link-state";
import { forwardedClientHeaders } from "@/lib/server-forwarded";

import B2BSignForm from "./B2BSignForm";

interface PageProps {
  params: Promise<{ token: string }>;
}

function apiBase(): string {
  return (
    process.env.INTERNAL_API_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    "http://localhost:8000"
  );
}

async function fetchView(
  token: string,
): Promise<{ view: PublicSignView } | { status: number | null }> {
  try {
    const res = await fetch(
      `${apiBase()}/api/public/b2b-sign/${encodeURIComponent(token)}`,
      { cache: "no-store", headers: await forwardedClientHeaders() },
    );
    if (!res.ok) return { status: res.status };
    return { view: (await res.json()) as PublicSignView };
  } catch {
    return { status: null };
  }
}

export default async function B2BSignPage({ params }: PageProps) {
  const { token } = await params;
  const result = await fetchView(token);
  if (!("view" in result)) {
    return <PublicLinkUnavailable failure={publicLinkFailure(result.status)} />;
  }
  const view = result.view;
  const dayPl = (value: string) =>
    new Date(value).toLocaleDateString("pl-PL", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      timeZone: "Europe/Warsaw",
    });
  const expires = view.expires_at ? dayPl(view.expires_at) : null;
  const signedPdfUntil = view.signed_pdf_until ? dayPl(view.signed_pdf_until) : null;

  return (
    <div className="mx-auto max-w-2xl px-4 py-10 md:px-6 md:py-16">
      <p className="mb-6 text-sm font-semibold text-foreground">B2B Network · podpis umowy</p>
      <div className="mb-2 flex items-center gap-3">
        <FileSignature className="h-7 w-7 text-primary" aria-hidden />
        <h1 className="text-2xl font-semibold">Umowa o współpracy B2B nr {view.contract_number}</h1>
      </div>
      <p className="mb-1 text-muted-foreground">Podpisuje: {view.contractor_name}</p>
      <p className="mb-8 text-sm text-muted-foreground">
        Umowa przenosi autorskie prawa majątkowe, dlatego prawo wymaga{" "}
        <strong>kwalifikowanego podpisu elektronicznego</strong>. Zwykły podpis, zaawansowany
        ani profil zaufany nie wystarczą.
        {expires ? ` Link ważny do ${expires}.` : ""}
      </p>
      <B2BSignForm token={token} initialState={view.status} signedPdfUntil={signedPdfUntil} />
    </div>
  );
}
