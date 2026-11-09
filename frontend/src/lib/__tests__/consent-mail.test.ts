import { describe, expect, it } from "vitest";

import {
  buildConsentRequest,
  consentClientLabel,
  consentMailStatus,
  fillSupplierName,
  isPkoClient,
  zobReference,
} from "@/lib/consent-mail";

describe("zobReference", () => {
  it("normalizuje oba zapisy numeru z rekrutacji", () => {
    expect(zobReference("ZOB-3109", null)).toBe("ZOB-3109");
    expect(zobReference("ZOB 2996", null)).toBe("ZOB-2996");
    expect(zobReference("zob-1", null)).toBe("ZOB-1");
  });

  it("bez numeru u klienta bierze go z nazwy rekrutacji", () => {
    expect(zobReference(null, "Programista Java (ZOB-3100)")).toBe("ZOB-3100");
    expect(zobReference("", "ZOB-3103 usługi programistyczne")).toBe("ZOB-3103");
  });

  it("bez numeru nigdzie nie zgaduje", () => {
    expect(zobReference("42961", "Programista Java")).toBeNull();
    expect(zobReference(null, null)).toBeNull();
  });
});

describe("buildConsentRequest", () => {
  it("uzupełnia temat, osobę, numer i firmę", () => {
    const mail = buildConsentRequest("Anna Fikcyjna", "ZOB-3109");
    expect(mail.subject).toBe("ZOB-3109 - zgoda na przetwarzanie danych osobowych");
    expect(mail.body).toContain("Ja, Anna Fikcyjna, wyrażam zgodę na przetwarzanie przez PKO Bank Polski");
    expect(mail.body).toContain("przekazanym przez B2B.net S.A. („Oferent”) w ramach zapytania ofertowego nr ZOB-3109.");
    expect(mail.body).not.toMatch(/\[|xxxx/);
  });
});

describe("fillSupplierName", () => {
  it("podmienia pusty wzór i zaznacza miejsce", () => {
    const parts = fillSupplierName("przekazanym przez [Nazwa Dostawcy] („Oferent”)");
    expect(parts.map((part) => part.value).join("")).toBe("przekazanym przez B2B.net S.A. („Oferent”)");
    expect(parts.filter((part) => part.filled)).toEqual([{ value: "B2B.net S.A.", filled: true }]);
  });

  it("tekst bez wzoru zostaje bez zmian", () => {
    expect(fillSupplierName("przekazanym przez PKO FINAT")).toEqual([
      { value: "przekazanym przez PKO FINAT", filled: false },
    ]);
  });
});

describe("isPkoClient", () => {
  it("rozpoznaje PKO po obu nazwach klienta, nie po fragmencie słowa", () => {
    expect(isPkoClient("PKO BP")).toBe(true);
    expect(isPkoClient("Powszechna Kasa Oszczędności Bank Polski S.A")).toBe(true);
    expect(isPkoClient("Spko Sp. z o.o.")).toBe(false);
    expect(isPkoClient(null)).toBe(false);
  });
});

describe("consentMailStatus", () => {
  const CANDIDATE = "anna@example.com";
  const thread = (subject: string | null, direction: string, from: string) => ({
    subject,
    latest: { direction, from_address: from, sent_at: "2026-10-29T12:00:00Z", received_at: "2026-10-29T12:00:02Z" },
  });

  it("własna wiadomość to wysłana prośba", () => {
    const status = consentMailStatus(
      [thread("ZOB-3109 - zgoda na przetwarzanie danych osobowych", "sent", "rekruter@example.com")],
      "ZOB-3109",
      CANDIDATE,
    );
    expect(status).toEqual({ kind: "sent", at: "2026-10-29T12:00:00Z" });
  });

  it("kopia własnej prośby w skrzynce firmy nie jest odpowiedzią kandydata", () => {
    const status = consentMailStatus(
      [thread("ZOB-3109 - zgoda na przetwarzanie danych osobowych", "received", "rekruter@example.com")],
      "ZOB-3109",
      CANDIDATE,
    );
    expect(status?.kind).toBe("sent");
  });

  it("odpowiedź kandydata rozpoznaje po nadawcy, bez względu na wielkość liter", () => {
    const status = consentMailStatus(
      [thread("RE: ZOB 3109 zgoda", "received", "Anna@Example.com")],
      "ZOB-3109",
      CANDIDATE,
    );
    expect(status).toEqual({ kind: "replied", at: "2026-10-29T12:00:02Z" });
  });

  it("nie myli innego zapytania, innego tematu ani szkicu z prośbą", () => {
    const zgoda = "ZOB-3109 - zgoda na przetwarzanie danych osobowych";
    expect(consentMailStatus([thread("ZOB-31090 - zgoda", "sent", "a@b.pl")], "ZOB-3109", CANDIDATE)).toBeNull();
    expect(consentMailStatus([thread("ZOB-3109 stawka", "sent", "a@b.pl")], "ZOB-3109", CANDIDATE)).toBeNull();
    expect(consentMailStatus([thread(zgoda, "draft", "a@b.pl")], "ZOB-3109", CANDIDATE)).toBeNull();
    expect(consentMailStatus([thread(null, "sent", "a@b.pl")], "ZOB-3109", CANDIDATE)).toBeNull();
  });

  it("bez adresu kandydata nie ogłasza odpowiedzi", () => {
    const status = consentMailStatus([thread("ZOB-3109 zgoda", "received", "anna@example.com")], "ZOB-3109", null);
    expect(status?.kind).toBe("sent");
  });
});

describe("consentClientLabel", () => {
  it("skraca nazwę PKO z rejestru, resztę zostawia", () => {
    expect(consentClientLabel("Powszechna Kasa Oszczędności Bank Polski S.A")).toBe("PKO BP");
    expect(consentClientLabel("Inny Bank")).toBe("Inny Bank");
    expect(consentClientLabel(null)).toBe("Klient");
  });
});
