import type { EmailMessage } from "@/lib/api";

/**
 * Na którą wiadomość odpowiada „Odpowiedz” w wątku (runda 6 audytu).
 *
 * Do 26.09.2026 przycisk brał OSTATNIĄ wiadomość wątku. Gdy była to nasza
 * wysłana wiadomość, Graph budował odpowiedź do nas samych (adresatem był
 * nadawca = właściciel skrzynki) albo odmawiał, a backend oddawał 500.
 * Odpowiadamy więc na ostatnią wiadomość PRZYCHODZĄCĄ; gdy kandydat jeszcze
 * nic nie napisał — otwieramy nowy mail do adresata ostatniej wysłanej.
 */
export type ReplyPlan =
  | { mode: "reply"; replyTo: EmailMessage }
  | { mode: "new"; defaultTo: string }
  | null;

export function planThreadReply(
  messages: readonly EmailMessage[],
  clicked?: EmailMessage,
): ReplyPlan {
  if (clicked && clicked.direction === "received") {
    return { mode: "reply", replyTo: clicked };
  }
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i].direction === "received") {
      return { mode: "reply", replyTo: messages[i] };
    }
  }
  const lastSent = clicked ?? messages[messages.length - 1];
  const to = lastSent?.to_addresses?.find((r) => r.address)?.address;
  return to ? { mode: "new", defaultTo: to } : null;
}
