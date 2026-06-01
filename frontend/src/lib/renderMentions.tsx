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
 * Renderuje treść notatki / wiadomości z @email-mentions zastąpionymi
 * MentionBadge'ami. Zachowuje białe znaki (renderuj w `<span class="whitespace-pre-line">`).
 *
 * Email który nie pasuje do żadnego usera w `usersByEmail` dostaje fallback
 * `<span class="text-blue-600">@email</span>` – i tak czytelne, ale bez nazwy.
 */
export function renderWithMentions(
  content: string,
  usersByEmail: UsersByEmail,
): ReactNode {
  if (!content) return null;
  const parts: ReactNode[] = [];
  let lastIdx = 0;
  let key = 0;

  // Reset regex state via fresh iteration via matchAll.
  for (const match of content.matchAll(EMAIL_RE)) {
    const idx = match.index ?? 0;
    if (idx > lastIdx) {
      parts.push(
        <Fragment key={`t${key++}`}>{content.slice(lastIdx, idx)}</Fragment>,
      );
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
