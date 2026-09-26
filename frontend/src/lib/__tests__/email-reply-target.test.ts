import { describe, expect, it } from "vitest";

import type { EmailMessage } from "@/lib/api";
import { planThreadReply } from "@/lib/email-reply-target";

function msg(id: number, direction: EmailMessage["direction"], to = "kandydat@firma.pl") {
  return {
    id,
    direction,
    from_address: direction === "sent" ? "me@b2bnetwork.pl" : "kandydat@firma.pl",
    to_addresses: [{ address: to }],
  } as unknown as EmailMessage;
}

describe("planThreadReply (runda 6 audytu)", () => {
  it("odpowiada na ostatnią PRZYCHODZĄCĄ, nie na własną wysłaną", () => {
    const thread = [msg(1, "received"), msg(2, "sent")];
    expect(planThreadReply(thread)).toEqual({ mode: "reply", replyTo: thread[0] });
  });

  it("klik „Odpowiedz” na własnej wysłanej też idzie do ostatniej przychodzącej", () => {
    const thread = [msg(1, "received"), msg(2, "sent")];
    expect(planThreadReply(thread, thread[1])).toEqual({
      mode: "reply",
      replyTo: thread[0],
    });
  });

  it("bez przychodzącej otwiera nowy mail do adresata wysłanej", () => {
    const thread = [msg(1, "sent")];
    expect(planThreadReply(thread)).toEqual({
      mode: "new",
      defaultTo: "kandydat@firma.pl",
    });
  });

  it("klik na przychodzącej odpowiada na nią", () => {
    const thread = [msg(1, "received"), msg(2, "received")];
    expect(planThreadReply(thread, thread[0])).toEqual({
      mode: "reply",
      replyTo: thread[0],
    });
  });
});
