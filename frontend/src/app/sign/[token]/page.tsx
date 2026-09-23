/**
 * Public signing page — served at /sign/{token}.
 *
 * The external consultant downloads the contract PDF, signs it with their own
 * qualified-signature tool (offline), and uploads the signed PAdES. The server
 * validates it (pyHanko + EU DSS). KIR-free upload-and-validate pas.
 *
 * Odmowa (4xx: wygasły / odwołany / wykorzystany / nieznany token) i awaria
 * (5xx, brak odpowiedzi) mają własne komunikaty — nie ogólne 404 aplikacji.
 */
import { PublicLinkUnavailable } from "@/components/public/PublicLinkUnavailable";
import { publicLinkFailure } from "@/lib/public-link-state";
import { forwardedClientHeaders } from "@/lib/server-forwarded";
import { FileSignature } from "lucide-react";

import SignForm from "./SignForm";

interface PageProps {
  params: Promise<{ token: string }>;
}

interface SignMeta {
  contract_id: number;
  signer_name: string;
  signature_type: string;
  provider: string;
  party: string;
  status: string;
  already_signed: boolean;
  expires_at: string | null;
}

function apiBase(): string {
  return (
    process.env.INTERNAL_API_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    "http://localhost:8000"
  );
}

async function fetchMeta(
  token: string,
): Promise<{ meta: SignMeta } | { status: number | null }> {
  try {
    const res = await fetch(`${apiBase()}/api/public/sign/${token}`, {
      cache: "no-store",
      // FE-N01: limit zapytań per odwiedzający, nie per kontener frontu.
      headers: await forwardedClientHeaders(),
    });
    if (!res.ok) return { status: res.status };
    return { meta: (await res.json()) as SignMeta };
  } catch {
    return { status: null };
  }
}

export default async function SignPage({ params }: PageProps) {
  const { token } = await params;
  const result = await fetchMeta(token);
  if (!("meta" in result)) {
    return <PublicLinkUnavailable failure={publicLinkFailure(result.status)} />;
  }
  const meta = result.meta;

  const expiresLabel = meta.expires_at
    ? new Date(meta.expires_at).toLocaleDateString("pl-PL", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
      })
    : null;

  return (
    <div className="max-w-2xl mx-auto px-6 py-12 md:py-16">
      <div className="flex items-center gap-3 mb-2">
        <FileSignature className="h-7 w-7 text-primary" />
        <h1 className="text-2xl font-semibold">Podpis umowy B2B</h1>
      </div>
      <p className="text-muted-foreground mb-1">
        Umowa nr {meta.contract_id} — {meta.signer_name}
      </p>
      <p className="text-sm text-muted-foreground mb-8">
        Wymagany podpis kwalifikowany (QES).
        {expiresLabel ? ` Link ważny do ${expiresLabel}.` : ""}
      </p>

      <SignForm token={token} alreadySigned={meta.already_signed} />
    </div>
  );
}
