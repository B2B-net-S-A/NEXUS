import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import type { InviteLink } from "@/lib/api/careerLinks";
import { findingsFromApproveError, normalizePublicProfile } from "@/lib/api/careerLinks";

import {
  activeLinkForJob,
  approveBlockedReason,
  hostFromUrl,
  isSlugFormatValid,
  liveFindings,
  paramsTagline,
  removeExcerpt,
} from "../share-utils";

function link(overrides: Partial<InviteLink>): InviteLink {
  return {
    token: "t",
    url: "https://x/apply/t",
    job: { id: 1, title: "A" },
    label: null,
    expires_at: null,
    revoked: false,
    use_count: 0,
    last_used_at: null,
    created_at: "2026-09-01T00:00:00Z",
    status: "active",
    ...overrides,
  };
}

describe("share-utils", () => {
  it("usuwa fragment i sprząta tylko miejsce cięcia", () => {
    expect(removeExcerpt("Opis. Budżet do 180 zł/h. Dalej...", "Budżet do 180 zł/h")).toBe(
      "Opis. Dalej...",
    );
    expect(removeExcerpt("Kontakt: jan@x.pl dziś", "jan@x.pl")).toBe("Kontakt: dziś");
    expect(removeExcerpt("bez zmian", "nie ma")).toBe("bez zmian");
  });

  it("znalezisko znika, gdy fragmentu nie ma już w tekście", () => {
    const f = [
      { code: "money", message: "m", excerpt: "180 zł/h" },
      { code: "contact", message: "c", excerpt: null },
    ];
    expect(liveFindings(f, "bez kwoty")).toEqual([f[1]]);
    expect(liveFindings(f, "stawka 180 ZŁ/H")).toHaveLength(2);
  });

  it("powód blokady nazywa kategorię", () => {
    expect(approveBlockedReason([{ code: "money", message: "", excerpt: null }])).toBe(
      "Usuń kwotę z opisu, aby zatwierdzić.",
    );
    expect(
      approveBlockedReason([
        { code: "money", message: "", excerpt: null },
        { code: "client_name", message: "", excerpt: null },
      ]),
    ).toBe("Usuń oznaczone fragmenty z opisu, aby zatwierdzić.");
  });

  it("slug zgodny z regułą backendu", () => {
    expect(isSlugFormatValid("marta-n")).toBe(true);
    expect(isSlugFormatValid("ab")).toBe(false);
    expect(isSlugFormatValid("-marta")).toBe(false);
    expect(isSlugFormatValid("marta-")).toBe(false);
    expect(isSlugFormatValid("Marta")).toBe(false);
    expect(isSlugFormatValid("a".repeat(41))).toBe(false);
  });

  it("aktywny link rekrutacji pomija wycofane i wygasłe", () => {
    const links = [
      link({ token: "a", status: "revoked", revoked: true }),
      link({ token: "b", status: "expired" }),
      link({ token: "c", status: "used" }),
    ];
    expect(activeLinkForJob(links, 1)?.token).toBe("c");
    expect(activeLinkForJob(links, 2)).toBeNull();
  });

  it("host i parametry podglądu", () => {
    expect(hostFromUrl("https://kariera.dynaminds.pl/marta-n")).toBe("kariera.dynaminds.pl");
    expect(hostFromUrl(null)).toBe("kariera.dynaminds.pl");
    expect(
      paramsTagline({
        city: "Warszawa",
        remote_policy: "hybrid",
        onsite_days_per_week: 2,
        seniority: "senior",
        contract: "B2B",
        start: null,
        duration: null,
      }),
    ).toBe("[warszawa · hybryda · b2b · senior]");
  });

  it("rozpoznaje odmowę zatwierdzenia i ignoruje inne 422", () => {
    const findings = [{ code: "money", message: "m", excerpt: "x" }];
    expect(
      findingsFromApproveError({
        response: { status: 422, data: { detail: { code: "PUBLIC_PROFILE_FINDINGS", findings } } },
      }),
    ).toEqual(findings);
    expect(
      findingsFromApproveError({ response: { status: 422, data: { detail: [{ loc: ["body"] }] } } }),
    ).toBeNull();
  });

  it("profil bez pól nie wywraca formularza", () => {
    const p = normalizePublicProfile(7, { items: [] } as never);
    expect(p.status).toBe("none");
    expect(p.findings).toEqual([]);
    expect(p.sections.must).toBe(true);
  });
});

describe("/preview/career-share zasiewa klucze funkcjami z careerLinks.ts", () => {
  const src = readFileSync(
    join(process.cwd(), "src/app/preview/career-share/page.tsx"),
    "utf8",
  );

  it("każdy klucz ładowany przy montowaniu jest zasiany", () => {
    for (const fn of [
      "shareablePublishedJobsQueryKey()",
      "inviteLinksQueryKey()",
      "jobPublicProfileQueryKey(101)",
      "careerLinkQueryKey()",
    ]) {
      expect(src, `brak zasiewu ${fn}`).toContain(`setQueryData(${fn}`);
    }
  });

  it("nie zasiewa kluczy literałami (rozjechałyby się z hookami)", () => {
    expect(src).not.toMatch(/setQueryData\(\s*\[/);
  });
});
