import { Fragment, ReactNode } from "react";

import type { ChatUserMini } from "@/types/job-chat";

const EMAIL_RE = /@([A-Za-z0-9._+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})/g;

export type UsersByEmail = Map<string, ChatUserMini>;

export function buildUsersByEmail(users: ChatUserMini[]): UsersByEmail {
  const map = new Map<string, ChatUserMini>();
  for (const u of users) {
    if (u.email) map.set(u.email.toLowerCase(), u);
  }
  return map;
}

/** Adresy oznaczone w treści (`@adres`, małe litery, bez powtórzeń) — ten sam wzorzec co parser serwera. */
export function mentionedEmails(content: string): string[] {
  if (!content) return [];
  return [...new Set(Array.from(content.matchAll(EMAIL_RE), (m) => m[1].toLowerCase()))];
}

interface MentionBadgeProps {
  email: string;
  user?: ChatUserMini;
}

export function MentionBadge({ email, user }: MentionBadgeProps) {
  const label = user?.name ?? email;
  return (
    <span
      title={user ? `${user.name} <${user.email}>` : email}
      className="inline-flex items-center px-1.5 py-0.5 rounded bg-primary/15 dark:bg-primary/25 text-primary text-[0.95em] font-medium"
    >
      @{label}
    </span>
  );
}

/**
 * `@wszyscy` — osoby przypisane do rekrutacji (czat i notatki rekrutacji,
 * 13.11.2026). Ten sam wzorzec co `_EVERYONE_RE` w `mention_parser.py`:
 * osobne słowo, nie część adresu (`biuro@wszyscy.pl`, `@wszyscy@firma.pl`).
 */
export const MENTION_EVERYONE_TOKEN = "@wszyscy";
const EVERYONE_SOURCE = String.raw`(?<![\w@.])@wszyscy(?![\w@.\-])`;
const EMAIL_OR_EVERYONE_RE = new RegExp(`${EMAIL_RE.source}|${EVERYONE_SOURCE}`, "gi");

export function hasEveryoneMention(content: string): boolean {
  return new RegExp(EVERYONE_SOURCE, "i").test(content ?? "");
}

export interface EveryoneMention {
  /** Imiona i nazwiska osób, które dostały wzmiankę (z zapisanych wzmianek). */
  names: string[];
}

/**
 * Renderuje treść notatki / wiadomości z @email-mentions zastąpionymi
 * MentionBadge'ami. Zachowuje białe znaki (renderuj w `<span class="whitespace-pre-line">`).
 *
 * Email który nie pasuje do żadnego usera w `usersByEmail` dostaje fallback
 * `<span class="text-blue-600">@email</span>` — i tak czytelne, ale bez nazwy.
 */
export function renderWithMentions(
  content: string,
  usersByEmail: UsersByEmail,
  everyone?: EveryoneMention,
): ReactNode {
  if (!content) return null;
  const parts: ReactNode[] = [];
  let lastIdx = 0;
  let key = 0;

  // Reset regex state via fresh iteration via matchAll.
  for (const match of content.matchAll(EMAIL_OR_EVERYONE_RE)) {
    const idx = match.index ?? 0;
    if (idx > lastIdx) {
      parts.push(
        <Fragment key={`t${key++}`}>{content.slice(lastIdx, idx)}</Fragment>,
      );
    }
    if (!match[1]) {
      parts.push(
        <span
          key={`m${key++}`}
          title={
            everyone?.names.length
              ? `Oznaczeni: ${everyone.names.join(", ")}`
              : "Wszyscy przypisani do rekrutacji"
          }
          className="inline-flex items-center px-1.5 py-0.5 rounded bg-primary/15 dark:bg-primary/25 text-primary text-[0.95em] font-medium"
        >
          @Wszyscy{everyone?.names.length ? ` (${everyone.names.length})` : ""}
        </span>,
      );
      lastIdx = idx + match[0].length;
      continue;
    }
    const email = match[1].toLowerCase();
    const user = usersByEmail.get(email);
    parts.push(
      user ? (
        <MentionBadge key={`m${key++}`} email={match[1]} user={user} />
      ) : (
        <span
          key={`m${key++}`}
          className="text-primary font-medium"
        >
          @{match[1]}
        </span>
      ),
    );
    lastIdx = idx + match[0].length;
  }
  if (lastIdx < content.length) {
    parts.push(<Fragment key={`t${key++}`}>{content.slice(lastIdx)}</Fragment>);
  }
  return <>{parts}</>;
}
