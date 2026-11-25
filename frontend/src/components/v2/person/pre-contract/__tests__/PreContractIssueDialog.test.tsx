import { describe, expect, it } from "vitest";

import { issueNotice } from "../PreContractIssueDialog";

const field = (key: string, sensitive: boolean) => ({ key, sensitive });

describe("issueNotice", () => {
  it("osoba fizyczna: PESEL, dowód i adres tylko w pliku", () => {
    const text = issueNotice({ fields: [field("partner_name", false), field("pesel", true)] });
    expect(text).toContain("PESEL");
    expect(text).toContain("NEXUS ich nie zapisuje");
  });

  it("kandydat z działalnością: bez zdania o PESEL-u i dowodzie", () => {
    const text = issueNotice({ fields: [field("partner_name", false), field("partner_nip", false)] });
    expect(text).not.toContain("PESEL");
    expect(text).not.toContain("dowód");
  });

  it("forma podpisu jak we wzorach od 24.11.2026: bez profilu zaufanego i podpisu osobistego", () => {
    const text = issueNotice({ fields: [] });
    expect(text).toContain("kwalifikowanym podpisem elektronicznym");
    expect(text).toContain("formie dokumentowej");
    expect(text).not.toMatch(/może podpisać[^.]*profilem zaufanym/);
  });
});
