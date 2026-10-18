/**
 * Wypis z komunikatów informacyjnych — `/wypis/{token}` (O12).
 *
 * Strona tylko czyta stan (GET niczego nie zmienia); wypis to przycisk.
 * Zły i nieznany link dają ten sam komunikat (serwer nie rozróżnia przyczyn),
 * a odpowiedź nie niesie danych osobowych.
 */
import { MailX } from "lucide-react";

import { UnsubscribeConfirm } from "@/components/care/announcements/UnsubscribeConfirm";
import { PublicLinkUnavailable } from "@/components/public/PublicLinkUnavailable";
import { publicLinkFailure } from "@/lib/public-link-state";
import { forwardedClientHeaders } from "@/lib/server-forwarded";

interface PageProps {
  params: Promise<{ token: string }>;
}

function apiBase(): string {
  return process.env.INTERNAL_API_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
}

async function fetchState(
  token: string,
): Promise<{ unsubscribed: boolean } | { status: number | null }> {
  try {
    const res = await fetch(
      `${apiBase()}/api/public/consultant-mail/unsubscribe/${encodeURIComponent(token)}`,
      { cache: "no-store", headers: await forwardedClientHeaders() },
    );
    if (!res.ok) return { status: res.status };
    const data = (await res.json()) as { unsubscribed?: unknown };
    return { unsubscribed: data.unsubscribed === true };
  } catch {
    return { status: null };
  }
}

export default async function UnsubscribePage({ params }: PageProps) {
  const { token } = await params;
  const result = await fetchState(token);
  if (!("unsubscribed" in result)) {
    return <PublicLinkUnavailable failure={publicLinkFailure(result.status)} />;
  }
  return (
    <div className="mx-auto max-w-xl px-4 py-10 sm:px-6">
      <div className="mb-4 flex items-center gap-3">
        <MailX className="h-7 w-7 text-primary" aria-hidden />
        <h1 className="text-2xl font-semibold">Wypis z wiadomości informacyjnych</h1>
      </div>
      <UnsubscribeConfirm token={token} unsubscribed={result.unsubscribed} />
    </div>
  );
}
