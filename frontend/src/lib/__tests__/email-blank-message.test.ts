import { describe, expect, it } from "vitest";

import type { EmailMessage } from "@/lib/api";
import { blankMessageLabel, isInviteReply } from "@/lib/email-blank-message";

function email(fields: Partial<EmailMessage>) {
  return {
    subject: "Rozmowa",
    body_html: null,
    body_text: "",
    body_preview: "",
    has_attachments: false,
    is_private_filtered: false,
    ...fields,
  } as EmailMessage;
}

describe("isInviteReply", () => {
  it.each([
    "Accepted: Rozmowa",
    "Tentative: Rozmowa",
    "Declined: Rozmowa",
    "Canceled: Rozmowa",
    "Cancelled: Rozmowa",
    "Zaakceptowano: Rozmowa",
    "Wstępnie zaakceptowano: Rozmowa",
    "Odrzucono: Rozmowa",
    "Anulowano: Rozmowa",
    "  accepted : Rozmowa",
  ])("rozpoznaje pusty „%s”", (subject) => {
    expect(isInviteReply(email({ subject }))).toBe(true);
  });

  it.each(["Re: Rozmowa", "Rozmowa: zaakceptowano", "Zaakceptowano umowę", "", null])(
    "nie myli innego tematu: %s",
    (subject) => {
      expect(isInviteReply(email({ subject }))).toBe(false);
    },
  );

  it("wiadomość z treścią nie jest pustą odpowiedzią", () => {
    expect(isInviteReply(email({ subject: "Accepted: Rozmowa", body_preview: "Będę" }))).toBe(false);
    expect(isInviteReply(email({ subject: "Accepted: Rozmowa", body_html: "<p>Będę</p>" }))).toBe(false);
  });

  it("załącznik i wiadomość prywatna to nie pusta odpowiedź", () => {
    expect(isInviteReply(email({ subject: "Accepted: Rozmowa", has_attachments: true }))).toBe(false);
    expect(isInviteReply(email({ subject: "Accepted: Rozmowa", is_private_filtered: true }))).toBe(false);
  });

  it("same białe znaki to brak treści", () => {
    expect(
      isInviteReply(email({ subject: "Accepted: Rozmowa", body_html: "", body_text: " \r\n", body_preview: " " })),
    ).toBe(true);
  });
});

describe("blankMessageLabel", () => {
  it("nazywa odpowiedź na zaproszenie", () => {
    expect(blankMessageLabel(email({ subject: "Accepted: Rozmowa" }))).toBe(
      "Odpowiedź na zaproszenie, bez treści",
    );
  });

  it("nazywa inną pustą wiadomość", () => {
    expect(blankMessageLabel(email({ subject: "Re: Rozmowa" }))).toBe("Ta wiadomość nie ma treści.");
  });

  it("nie ma opisu dla wiadomości z treścią, załącznikiem albo prywatnej", () => {
    expect(blankMessageLabel(email({ body_preview: "Treść" }))).toBeNull();
    expect(blankMessageLabel(email({ has_attachments: true }))).toBeNull();
    expect(blankMessageLabel(email({ is_private_filtered: true }))).toBeNull();
  });
});
