import type { EmailMessage } from "@/lib/api";

/**
 * Wiadomości bez treści w wątku kandydata.
 *
 * Outlook zapisuje odpowiedź na zaproszenie jako osobną, pustą wiadomość.
 * Rozpoznajemy ją po pustej treści i początku tematu, bo typu z Graphu
 * (`@odata.type`) nie zapisujemy w bazie. Zasady i pomiar:
 * `docs/claude/integracje/odpowiedzi-na-zaproszenia-bez-tresci.md`.
 */
type MessageContent = Pick<
  EmailMessage,
  | "subject"
  | "body_html"
  | "body_text"
  | "body_preview"
  | "has_attachments"
  | "is_private_filtered"
>;

export const INVITE_REPLY_LABEL = "Odpowiedź na zaproszenie, bez treści";
export const NO_CONTENT_LABEL = "Ta wiadomość nie ma treści.";

const INVITE_REPLY_SUBJECT =
  /^\s*(accepted|tentative|declined|cancell?ed|zaakceptowan[oe]|wst[eę]pnie zaakceptowan[oe]|odrzucon[oe]|anulowan[oe])\s*:/i;

function isBlank(email: MessageContent): boolean {
  return (
    !email.has_attachments &&
    !email.is_private_filtered &&
    ![email.body_html, email.body_text, email.body_preview].some((value) =>
      value?.trim(),
    )
  );
}

export function isInviteReply(email: MessageContent): boolean {
  return isBlank(email) && INVITE_REPLY_SUBJECT.test(email.subject ?? "");
}

/** Opis pustej wiadomości; `null`, gdy wiadomość ma co pokazać. */
export function blankMessageLabel(email: MessageContent): string | null {
  if (!isBlank(email)) return null;
  return isInviteReply(email) ? INVITE_REPLY_LABEL : NO_CONTENT_LABEL;
}
