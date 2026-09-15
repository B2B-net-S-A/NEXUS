/**
 * Notatka z @wzmianką → powiadomienie u wzmiankowanego użytkownika.
 *
 * `@stack`. Dawna wersja wysyłała `content_json` na nieistniejący endpoint
 * (`/api/candidates/{id}/notes`), pomijała się przy błędzie i kończyła się
 * cichym `return`. API: `POST /api/notes` (201), wzmianka `@<id użytkownika>`
 * (`services/mention_parser.py`), powiadomienie `note_mention`.
 */
import { test, expect, jsonOf } from "./helpers/api";
import { createCandidate } from "./helpers/entities";

interface NotificationList {
  items: Array<{ notification_type: string; link: string | null; title: string }>;
}

test.describe("Notatka ze wzmianką @stack", () => {
  test("wzmiankowany rekruter dostaje powiadomienie note_mention", async ({ admin, apiAs }) => {
    const recruiter = await apiAs("recruiter");
    const candidate = await createCandidate(admin.api);

    const note = await jsonOf<{ id: number; content: string; candidate_id: number }>(
      await admin.api.post("/api/notes", {
        data: {
          content: `Proszę o screening @${recruiter.userId} — kandydat ${candidate.lastname}`,
          candidate_id: candidate.id,
        },
      }),
      201,
      "POST /api/notes"
    );
    expect(note.candidate_id).toBe(candidate.id);

    const notifications = await jsonOf<NotificationList>(
      await recruiter.api.get("/api/notifications?limit=50"),
      200,
      "powiadomienia rekrutera"
    );
    const mention = notifications.items.find(
      (item) => item.notification_type === "note_mention" && item.title.includes(admin.name)
    );
    expect(mention, "powiadomienie o wzmiance u rekrutera").toBeDefined();
  });
});
