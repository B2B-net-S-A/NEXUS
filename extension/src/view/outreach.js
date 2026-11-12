// Recruiter Lite (decyzja Artura 12.11.2026): 30 InMaili miesięcznie, bez
// spotlightów i wspólnych projektów. Czyste funkcje: co panel radzi przed
// InMailem, jak pyta o odpowiedź i kogo na liście warto przejrzeć.
// Dane z `outreach` (/lookup), `inmail` (/me) i `last_contact` (/lookup-batch).

import { formatDate, formatMonthYear } from "./logic.js";

/** Kontakt zespołu „świeży” = ostatnie 30 dni. */
export const RECENT_DAYS = 30;
/** Ile InMaili zostało, gdy panel zaczyna ostrzegać. */
export const LOW_CREDITS = 5;

export function daysAgoLabel(days) {
  if (days == null) return "";
  if (days <= 0) return "dziś";
  if (days === 1) return "wczoraj";
  return `${days} dni temu`;
}

/** Stopień kontaktu z odczytanej strony („· 2nd”) → 1, 2, 3 albo null. */
export function degreeLabel(degree) {
  return degree === 1 || degree === 2 || degree === 3 ? `${degree}. stopień` : "";
}

/** Linia w menu: „InMaile w listopadzie: 12 z 30 · odpowiedzi 5”. */
export function inmailUsageLabel(inmail) {
  if (!inmail || inmail.credits_month == null) return "";
  const replies = inmail.replied_month ? ` · odpowiedzi ${inmail.replied_month}` : "";
  return `InMaile w tym miesiącu: ${inmail.sent_month ?? 0} z ${inmail.credits_month}${replies}`;
}

export function creditsLeft(inmail) {
  if (!inmail || inmail.credits_month == null) return null;
  return Math.max(0, inmail.credits_month - (inmail.sent_month ?? 0));
}

/**
 * Podpowiedź przed InMailem. Zwraca listę punktów (ton + tekst) i zalecany
 * rodzaj wiadomości, gdy jest tańszy od InMaila (`invitation`, `linkedin_message`).
 * Telefon nie zmienia rodzaju wiadomości — rekruter dzwoni poza panelem.
 *
 * @param {{outreach?: object|null, degree?: number|null, inmail?: object|null}} input
 */
export function inmailAdvice({ outreach = null, degree = null, inmail = null } = {}) {
  const checks = [];
  let cheaper = null;
  if (outreach?.has_phone) {
    checks.push({ tone: "warn", icon: "☎", text: "W NEXUSIE jest telefon do tej osoby. Zadzwoń najpierw, InMail zostaw na później." });
  }
  if (degree === 1) {
    checks.push({ tone: "ok", icon: "✓", text: "1. stopień: zwykła wiadomość nic nie kosztuje." });
    cheaper = "linkedin_message";
  } else if (degree === 2) {
    checks.push({ tone: "ok", icon: "✓", text: "2. stopień: zaproszenie z notatką nic nie kosztuje." });
    cheaper = "invitation";
  }
  const open = outreach?.open_inmail;
  if (open) {
    const refund = open.refund_until ? ` Odpowiedź do ${formatDate(open.refund_until)} odda kredyt.` : "";
    checks.push({ tone: "warn", icon: "!", text: `Twój InMail z ${formatDate(open.at)} czeka na odpowiedź. Drugi InMail to drugi kredyt.${refund}` });
  }
  const recent = outreach?.recent_contact;
  if (recent && !recent.is_me && (recent.days_ago ?? RECENT_DAYS + 1) <= RECENT_DAYS) {
    const who = recent.user_name || "Ktoś z zespołu";
    checks.push({ tone: "warn", icon: "!", text: `${who}: ${recent.channel_label || "kontakt"} ${daysAgoLabel(recent.days_ago)}. Uzgodnij, zanim napiszesz.` });
  }
  const left = creditsLeft(inmail);
  if (left != null && left <= LOW_CREDITS) {
    checks.push({ tone: "warn", icon: "!", text: left === 0 ? "Według zapisów w NEXUSIE InMaile na ten miesiąc się skończyły." : `Zostało ${left} InMaili w tym miesiącu.` });
  }
  if (!checks.length) checks.push({ tone: "ok", icon: "✓", text: "Nie widzę tańszej drogi: InMail ma tu sens." });
  return { checks, cheaper };
}

/** Pytanie „odpisała?” przy moim InMailu bez zapisanej odpowiedzi. */
export function replyPrompt(outreach) {
  const open = outreach?.open_inmail;
  if (!open || open.note_id == null) return null;
  const job = open.job_title ? ` · ${open.job_title}` : "";
  return {
    noteId: open.note_id,
    title: `Twój InMail z ${formatDate(open.at)}${job}`,
    refund: open.refund_until ? `Odpowiedź (także odmowa) do ${formatDate(open.refund_until)} oddaje kredyt InMail.` : "",
  };
}

export const REPLY_OUTCOMES = Object.freeze([
  { value: "interested", label: "Tak, chce rozmawiać", notice: "Zapisane: chce rozmawiać." },
  { value: "not_now", label: "Tak, nie teraz", notice: "Zapisane: odpowiedź „nie teraz”." },
  { value: "no_reply", label: "Bez odpowiedzi", notice: "Zapisane: bez odpowiedzi." },
]);

// ── Lista wyników ───────────────────────────────────────────────────────────

export function isRecentContact(lastContact) {
  return Boolean(lastContact) && (lastContact.days_ago ?? RECENT_DAYS + 1) <= RECENT_DAYS;
}

/** Do przejrzenia: nowe osoby i „w bazie” bez kontaktu zespołu w 30 dni. */
export function isTodo(item) {
  if (!item) return false;
  if (item.status === "new") return true;
  return item.status === "in_base" && !isRecentContact(item.last_contact);
}

export function triage(items) {
  const list = items || [];
  return {
    total: list.length,
    todo: list.filter(isTodo).length,
    inBase: list.filter((it) => it.status === "in_base" || it.status === "in_process").length,
    withPhone: list.filter((it) => it.has_phone && (it.status === "in_base" || it.status === "in_process")).length,
    recent: list.filter((it) => isRecentContact(it.last_contact)).length,
    offLimits: list.filter((it) => it.status === "off_limits").length,
    contractors: list.filter((it) => it.status === "contractor").length,
  };
}

/** Linia pod osobą na liście: świeży kontakt ostrzega, starszy tylko informuje. */
export function lastContactLine(lastContact) {
  if (!lastContact) return null;
  const who = lastContact.is_me ? "Ty" : lastContact.user_name || "zespół";
  const channel = lastContact.channel_label || "kontakt";
  if (isRecentContact(lastContact)) {
    return { tone: "warning", text: `${who}: ${channel} ${daysAgoLabel(lastContact.days_ago)}` };
  }
  const when = formatMonthYear(lastContact.at);
  return { tone: "muted", text: `Ostatni kontakt: ${when ? `${when} · ` : ""}${channel}` };
}

// ── Wyszukiwanie do Recruitera ──────────────────────────────────────────────

/** Tekst do schowka dla listy (jedna pozycja w linii — filtr firmy przyjmuje po jednej). */
export function listForClipboard(items) {
  return (items || []).filter(Boolean).join("\n");
}
