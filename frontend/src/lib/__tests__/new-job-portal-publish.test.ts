import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ default: {}, api: {} }));

import {
  listingDefaultsFromForm,
  portalPlanBlocker,
  publicDraftRequest,
  publishNewJobToPortals,
  type NewJobPortalPlan,
  type PortalPublishDeps,
} from "@/lib/new-job-portal-publish";
import { EMPTY_LISTING_OPTIONS } from "@/lib/api/jobPortals";
import { EMPTY_INTAKE_FORM, type IntakeForm } from "@/lib/job-request-intake";

const FORM: IntakeForm = {
  ...EMPTY_INTAKE_FORM,
  title: "Senior Java Developer",
  clientTitle: "Programista Java (ZOB 1)",
  must: ["Java", "Kafka"],
  nice: ["Kubernetes"],
  remotePolicy: "hybrid",
  onsiteDays: "2",
  city: " Warszawa ",
  rateBudget: "170",
  about: "Migracja płatności.",
};

const PLAN: NewJobPortalPlan = {
  portals: ["rocketjobs", "justjoinit"],
  draft: { publicTitle: "Senior Java Developer", subtitle: "Płatności", about: "Opis" },
  options: {
    ...EMPTY_LISTING_OPTIONS,
    category: "java",
    experience_level: "senior",
    working_time: "full_time",
    city: "Warszawa",
    workplace_type: "remote",
  },
};

function deps(overrides: Partial<PortalPublishDeps> = {}) {
  const calls: string[] = [];
  const base: PortalPublishDeps = {
    saveProfile: vi.fn(async () => void calls.push("profile")),
    approveProfile: vi.fn(async () => void calls.push("approve")),
    createLink: vi.fn(async () => void calls.push("link")),
    publish: vi.fn(async (_id, portal) => void calls.push(`publish:${portal}`)),
    ...overrides,
  };
  return { calls, deps: base };
}

describe("domyślne parametry ogłoszenia z formularza", () => {
  it("miasto, tryb i dni w biurze — bez kategorii i bez widełek (nigdy z budżetu)", () => {
    expect(listingDefaultsFromForm(FORM)).toEqual({
      ...EMPTY_LISTING_OPTIONS,
      working_time: "full_time",
      city: "Warszawa",
      workplace_type: "hybrid",
      office_days: 2,
    });
    expect(listingDefaultsFromForm({ ...FORM, remotePolicy: "onsite" })).toMatchObject({
      workplace_type: "office",
      office_days: null,
    });
    expect(listingDefaultsFromForm({ ...FORM, remotePolicy: "", city: "" })).toMatchObject({
      workplace_type: null,
      city: null,
      salary: null,
    });
  });

  it("ciało szkicu opisu publicznego", () => {
    const body = publicDraftRequest(FORM, { clientId: 7, requestText: "  mail  " });
    expect(body).toMatchObject({
      title: "Senior Java Developer",
      client_id: 7,
      description: "mail",
      must_skills: ["Java", "Kafka"],
      location: "Warszawa",
      remote_policy: "hybrid",
      onsite_days_per_week: 2,
    });
    expect(body.champion_profile).toHaveProperty("basics");
    expect(publicDraftRequest({ ...FORM, remotePolicy: "remote" }, { clientId: null, requestText: "" })).toMatchObject(
      { location: null, onsite_days_per_week: null, description: null },
    );
  });
});

describe("portalPlanBlocker", () => {
  it("bez portali nic nie blokuje", () => {
    expect(portalPlanBlocker({ ...PLAN, portals: [], draft: null })).toBeNull();
  });
  it("portale bez przygotowanego ogłoszenia", () => {
    expect(portalPlanBlocker({ ...PLAN, draft: null })).toContain("Przygotuj ogłoszenie");
  });
  it("braki parametrów, każdy raz", () => {
    const blocker = portalPlanBlocker({ ...PLAN, options: { ...PLAN.options, category: null } });
    expect(blocker).toBe("Wybierz kategorię ogłoszenia.");
  });
  it("kompletny plan", () => {
    expect(portalPlanBlocker(PLAN)).toBeNull();
  });
});

describe("publishNewJobToPortals", () => {
  it("kolejność z kontraktu", async () => {
    const { calls, deps: d } = deps();
    const out = await publishNewJobToPortals(9, PLAN, {}, d);
    expect(out).toEqual({ ok: true, published: ["rocketjobs", "justjoinit"] });
    expect(calls).toEqual(["profile", "approve", "link", "publish:rocketjobs", "publish:justjoinit"]);
    expect(d.publish).toHaveBeenCalledWith(9, "rocketjobs", PLAN.options);
  });

  it("bez portali nic nie woła", async () => {
    const { calls, deps: d } = deps();
    expect(await publishNewJobToPortals(9, { ...PLAN, portals: [] }, {}, d)).toEqual({ ok: true, published: [] });
    expect(calls).toEqual([]);
  });

  it("uwagi kontroli przy zatwierdzeniu zatrzymują wszystko", async () => {
    const { calls, deps: d } = deps({
      approveProfile: vi.fn(async () => {
        throw {
          response: {
            status: 422,
            data: { detail: { code: "PUBLIC_PROFILE_FINDINGS", findings: [{ code: "client_name", message: "Nazwa klienta w opisie.", excerpt: "X" }] } },
          },
        };
      }),
    });
    const out = await publishNewJobToPortals(9, PLAN, {}, d);
    expect(out).toEqual({ ok: false, published: [], message: "opis publiczny ma uwagi kontroli: Nazwa klienta w opisie." });
    expect(calls).toEqual(["profile"]);
  });

  it("awaria linku nie publikuje na portalach", async () => {
    const { calls, deps: d } = deps({
      createLink: vi.fn(async () => {
        throw { response: { status: 400, data: { detail: "Rekrutacja nie jest opublikowana." } } };
      }),
    });
    const out = await publishNewJobToPortals(9, PLAN, {}, d);
    expect(out.ok).toBe(false);
    expect(out.ok === false && out.message).toContain("Rekrutacja nie jest opublikowana.");
    expect(calls).toEqual(["profile", "approve"]);
  });

  it("awaria jednego portalu nie blokuje drugiego", async () => {
    const { calls, deps: d } = deps({
      publish: vi.fn(async (_id: number, portal: string) => {
        if (portal === "rocketjobs") throw { response: { status: 409, data: { detail: "Konto niepołączone." } } };
        calls.push(`publish:${portal}`);
      }),
    });
    const out = await publishNewJobToPortals(9, PLAN, { rocketjobs: "RocketJobs" }, d);
    expect(out).toEqual({ ok: false, published: ["justjoinit"], message: "RocketJobs: Konto niepołączone." });
    expect(calls).toContain("publish:justjoinit");
  });

  it("brak szkicu nie woła API", async () => {
    const { calls, deps: d } = deps();
    const out = await publishNewJobToPortals(9, { ...PLAN, draft: null }, {}, d);
    expect(out.ok).toBe(false);
    expect(calls).toEqual([]);
  });
});
