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
    expect(planThreadReply(thread, undefined, "kandydat@firma.pl")).toEqual({
      mode: "reply",
      replyTo: thread[0],
    });
  });

  it("runda 7: nie odpowiada na mail HM-a ani kolegi w tym samym wątku", () => {
    const hm = {
      id: 3,
      direction: "received",
      from_address: "hm@klient.pl",
      to_addresses: [{ address: "me@b2bnetwork.pl" }],
    } as unknown as EmailMessage;
    const thread = [msg(1, "received"), msg(2, "sent", "hm@klient.pl"), hm, msg(4, "sent")];
    expect(planThreadReply(thread, thread[3], "Kandydat@Firma.pl ")).toEqual({
      mode: "reply",
      replyTo: thread[0],
    });
  });

  it("runda 7: bez maila od kandydata otwiera nowy mail DO KANDYDATA", () => {
    const hm = {
      id: 3,
      direction: "received",
      from_address: "hm@klient.pl",
      to_addresses: [],
    } as unknown as EmailMessage;
    expect(planThreadReply([msg(2, "sent", "hm@klient.pl"), hm], undefined, "kandydat@firma.pl")).toEqual({
      mode: "new",
      defaultTo: "kandydat@firma.pl",
    });
  });

  it("klik „Odpowiedz” na własnej wysłanej też idzie do ostatniej przychodzącej", () => {
    const thread = [msg(1, "received"), msg(2, "sent")];
    expect(planThreadReply(thread, thread[1], "kandydat@firma.pl")).toEqual({
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
