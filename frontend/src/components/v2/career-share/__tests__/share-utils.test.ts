import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import type { InviteLink } from "@/lib/api/careerLinks";
import { findingsFromApproveError, normalizePublicProfile } from "@/lib/api/careerLinks";

import {
  absoluteUrl,
  activeLinkForJob,
  approveBlockedReason,
  careerPreviewHost,
  displayUrl,
  effectivePublicTitle,
  hostFromUrl,
  recruiterLinkPrefix,
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
    expect(hostFromUrl(null)).toBe("");
    // Adres względny = host bieżącej strony (jsdom: localhost:3000).
    expect(hostFromUrl("/kariera/p/marta-n")).toBe(window.location.host);
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

describe("adresy strony kariery — z API, nie ze stałej domeny", () => {
  const here = window.location.host;

  it("prefiks stałego linku: recruiter_base_url → adres linku bez sluga → bieżący host", () => {
    expect(
      recruiterLinkPrefix({ link: null, recruiter_base_url: "https://kariera.dynaminds.pl/" }),
    ).toBe("kariera.dynaminds.pl/");
    expect(
      recruiterLinkPrefix({ link: null, recruiter_base_url: "https://nexus.dynaminds.pl/kariera/p" }),
    ).toBe("nexus.dynaminds.pl/kariera/p/");
    expect(
      recruiterLinkPrefix({
        link: { slug: "marta-n", public_url: "https://kariera.dynaminds.pl/marta-n", created_at: "", visit_count: 0 },
      }),
    ).toBe("kariera.dynaminds.pl/");
    expect(
      recruiterLinkPrefix({
        link: { slug: "marta-n", public_url: "/kariera/p/marta-n", created_at: "", visit_count: 0 },
      }),
    ).toBe(`${here}/kariera/p/`);
    expect(recruiterLinkPrefix({ link: null })).toBe(`${here}/kariera/p/`);
  });

  it("host podglądu: adres linku → base_url → bieżący host", () => {
    expect(careerPreviewHost("https://kariera.dynaminds.pl/r/x", "https://nexus.dynaminds.pl")).toBe(
      "kariera.dynaminds.pl",
    );
    expect(careerPreviewHost(null, "https://nexus.dynaminds.pl")).toBe("nexus.dynaminds.pl");
    expect(careerPreviewHost(null, null)).toBe(here);
  });

  it("adres do wyświetlenia bez protokołu, do skopiowania — bezwzględny", () => {
    expect(displayUrl("https://nexus.dynaminds.pl/kariera/p/")).toBe("nexus.dynaminds.pl/kariera/p/");
    expect(absoluteUrl("/kariera/p/marta-n")).toBe(`${window.location.origin}/kariera/p/marta-n`);
    expect(absoluteUrl("https://kariera.dynaminds.pl/marta-n")).toBe(
      "https://kariera.dynaminds.pl/marta-n",
    );
  });

  it("tytuł efektywny: wpisany → domyślny → tytuł rekrutacji", () => {
    expect(effectivePublicTitle("  Java Dev ", "Senior Java", "Nordea: Senior Java")).toBe("Java Dev");
    expect(effectivePublicTitle("  ", "Senior Java", "Nordea: Senior Java")).toBe("Senior Java");
    expect(effectivePublicTitle(null, null, "Nordea: Senior Java")).toBe("Nordea: Senior Java");
    expect(effectivePublicTitle(undefined, undefined, undefined)).toBe("Rekrutacja");
  });

  it("normalizacja profilu toleruje brak pól tytułu (starszy backend)", () => {
    const p = normalizePublicProfile(1, {});
    expect(p.public_title).toBeNull();
    expect(p.default_title).toBeNull();
    expect(p.effective_title).toBeNull();
    expect(normalizePublicProfile(1, { public_title: "  " }).public_title).toBeNull();
  });
});
