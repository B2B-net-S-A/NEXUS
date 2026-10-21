// „Powiadom oznaczonych o zmianie” przy edycji notatki (21.10.2026).
// Lustro `to_renotify` w `PATCH /api/notes/{id}`: osoby oznaczone przed
// i po edycji, bez autora, tylko gdy treść się zmieniła. Nowo dopisane
// osoby dostają zwykłą wzmiankę niezależnie od pola.

import { mentionedEmails, type UsersByEmail } from "@/lib/renderMentions";
import type { ChatUserMini } from "@/types/job-chat";

export function notifyOnEditRecipients(
  before: string,
  after: string,
  usersByEmail: UsersByEmail,
  currentUserId: number | undefined,
): ChatUserMini[] {
  if (before.trim() === after.trim()) return [];
  const was = new Set(mentionedEmails(before));
  return mentionedEmails(after)
    .filter((email) => was.has(email))
    .map((email) => usersByEmail.get(email))
    .filter(
      (user): user is ChatUserMini =>
        user != null && Number(user.id) !== Number(currentUserId),
    );
}

/** „Anna Nowak”, „Anna Nowak i Piotr Lis”, „Anna Nowak i 2 inne osoby”. */
export function recipientsLabel(users: readonly ChatUserMini[]): string {
  const names = users.map((u) => u.name || u.email);
  if (names.length <= 2) return names.join(" i ");
  const rest = names.length - 1;
  const few = rest % 10 >= 2 && rest % 10 <= 4 && (rest % 100 < 12 || rest % 100 > 14);
  return `${names[0]} i ${rest} ${few ? "inne osoby" : "innych osób"}`;
}
