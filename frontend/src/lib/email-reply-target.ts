import type { EmailMessage } from "@/lib/api";

/**
 * Na którą wiadomość odpowiada „Odpowiedz” w wątku (runda 6 audytu).
 *
 * Do 26.09.2026 przycisk brał OSTATNIĄ wiadomość wątku. Gdy była to nasza
 * wysłana wiadomość, Graph budował odpowiedź do nas samych (adresatem był
 * nadawca = właściciel skrzynki) albo odmawiał, a backend oddawał 500.
 * Odpowiadamy więc na ostatnią wiadomość PRZYCHODZĄCĄ OD KANDYDATA; gdy
 * kandydat jeszcze nic nie napisał — otwieramy nowy mail do kandydata.
 */
export type ReplyPlan =
  | { mode: "reply"; replyTo: EmailMessage }
  | { mode: "new"; defaultTo: string }
  | null;

export function planThreadReply(
  messages: readonly EmailMessage[],
  clicked?: EmailMessage,
  candidateEmail?: string | null,
): ReplyPlan {
  if (clicked && clicked.direction === "received") {
    return { mode: "reply", replyTo: clicked };
  }
  // Runda 7 (R7-V1-2): „ostatnia przychodząca” bywała mailem HM-a klienta
  // albo kolegi z kopii w tym samym wątku — odpowiedź dla kandydata szła do
  // nich. Bez kliknięcia konkretnej wiadomości odpowiadamy WYŁĄCZNIE na mail
  // od kandydata (lustro `reply_email` w backendzie).
  const ownAddress = candidateEmail?.trim() || null;
  const own = ownAddress?.toLowerCase() ?? null;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const m = messages[i];
    if (
      m.direction === "received" &&
      own !== null &&
      (m.from_address ?? "").trim().toLowerCase() === own
    ) {
      return { mode: "reply", replyTo: m };
    }
  }
  if (ownAddress) return { mode: "new", defaultTo: ownAddress };
  const lastSent = clicked ?? messages[messages.length - 1];
  const to = lastSent?.to_addresses?.find((r) => r.address)?.address;
  return to ? { mode: "new", defaultTo: to } : null;
}
