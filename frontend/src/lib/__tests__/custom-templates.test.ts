import { describe, expect, it } from "vitest";

import type { CustomFieldDef, CustomVersion } from "@/lib/api/customTemplates";
import {
  changeSummary,
  checkTone,
  citeStateLabel,
  fieldsPayload,
  groupFields,
  initialStep,
  invalidFieldKeys,
  isCustomTypeKey,
  offeredForClient,
  patchField,
  submitBlockers,
  templateStatusLabel,
} from "@/lib/custom-templates";

function field(key: string, extra: Partial<CustomFieldDef> = {}): CustomFieldDef {
  return {
    key,
    label: key,
    kind: "text",
    group: "Dokument",
    source: "manual",
    source_label: "ręcznie",
    required: false,
    sensitive: false,
    help: null,
    options: [],
    item_keys: [],
    ...extra,
  };
}

function version(extra: Partial<CustomVersion> = {}): CustomVersion {
  return {
    id: 1,
    version_no: 1,
    status: "draft",
    status_label: "szkic",
    name: "Umowa o szkolenie stacjonarne",
    kind: "contract",
    kind_label: "Umowa",
    description: "",
    client_scope: "all",
    client_ids: [],
    signatories: "both",
    signature_form: "any",
    origin: "base",
    base_key: "training_agreement",
    instruction: null,
    ai_used: false,
    created_by_name: "Osoba Testowa",
    created_at: null,
    submitted_by_name: null,
    submitted_at: null,
    reviewed_by_name: null,
    reviewed_at: null,
    review_note: null,
    fields: [field("partner.nip")],
    problems: [],
    checks: [],
    ...extra,
  };
}

describe("groupFields", () => {
  it("keeps the order of first appearance of each group", () => {
    const groups = groupFields([
      field("a", { group: "Partner" }),
      field("b", { group: "Szkolenie" }),
      field("c", { group: "Partner" }),
      field("d", { group: "" }),
    ]);
    expect(groups.map((g) => g.group)).toEqual(["Partner", "Szkolenie", "Dokument"]);
    expect(groups[0].fields.map((f) => f.key)).toEqual(["a", "c"]);
  });
});

describe("invalidFieldKeys", () => {
  const fields = [
    field("name", { required: true }),
    field("fee", { kind: "money", required: true }),
    field("day", { kind: "date" }),
    field("mail", { kind: "email" }),
    field("mode", { kind: "select", options: [["remote", "zdalnie"]] }),
    field("agree", { kind: "bool", required: true }),
  ];

  it("reports missing required and malformed values", () => {
    expect(
      invalidFieldKeys(fields, { fee: "dużo", day: "jutro", mail: "x@", mode: "office" }),
    ).toEqual(["name", "fee", "day", "mail", "mode", "agree"]);
  });

  it("accepts Polish money notation and false as a filled bool", () => {
    expect(
      invalidFieldKeys(fields, {
        name: "Jan",
        fee: "6 200,50 zł",
        day: "2026-12-01",
        mail: "jan@example.com",
        mode: "remote",
        agree: false,
      }),
    ).toEqual([]);
  });
});

describe("offeredForClient", () => {
  it("limits selected-scope templates to listed clients", () => {
    const selected = { client_scope: "selected" as const, client_ids: [5, 8] };
    expect(offeredForClient(selected, 5)).toBe(true);
    expect(offeredForClient(selected, 6)).toBe(false);
    expect(offeredForClient(selected, null)).toBe(false);
    expect(offeredForClient({ client_scope: "all", client_ids: [] }, null)).toBe(true);
  });
});

describe("submitBlockers", () => {
  it("lists server problems, blocking checks and missing settings", () => {
    const blockers = submitBlockers(
      version({
        problems: ["Nieznane pole „x” (treść)"],
        checks: [
          {
            key: "art53_pr_aut",
            state: "block",
            text: "Ustaw podpis na papierze",
            cite: "art. 53 pr. aut.",
            cite_kind: "law",
            cite_state: "unverified",
          },
        ],
        client_scope: "selected",
        fields: [],
        name: " ",
      }),
    );
    expect(blockers).toEqual([
      "Nieznane pole „x” (treść)",
      "Ustaw podpis na papierze",
      "Wzór nie ma żadnego pola do wypełnienia.",
      "Wybierz klientów, dla których jest wzór.",
      "Podaj nazwę wzoru.",
    ]);
  });

  it("is empty for a ready draft and for no version", () => {
    expect(submitBlockers(version())).toEqual([]);
    expect(submitBlockers(null)).toEqual([]);
  });
});

describe("studio helpers", () => {
  it("opens pending templates at the save step and drafts at fields", () => {
    const detail = {
      id: 1,
      withdrawn_at: null,
      withdrawn_by_name: null,
      withdrawn_reason: null,
      active: null,
      history: [],
      can_edit: true,
      can_review: false,
      can_withdraw: false,
      can_new_version: false,
    };
    expect(initialStep(null)).toBe("brief");
    expect(initialStep({ ...detail, working: version() })).toBe("draft");
    expect(initialStep({ ...detail, working: version({ status: "pending" }) })).toBe("save");
    expect(initialStep({ ...detail, working: null })).toBe("save");
  });

  it("summarises changes", () => {
    expect(
      changeSummary(
        [
          { op: "replace", i: 1, before: "a", after: "b", context: "", reason: "" },
          { op: "replace", i: 2, before: "a", after: "b", context: "", reason: "" },
          { op: "insert_after", i: 3, before: "", after: "c", context: "x", reason: "" },
        ],
        11,
      ),
    ).toBe("Zmienione: 2 · dodane: 1 · usunięte: 0 · pola: 11");
  });

  it("patches one field immutably and strips display-only keys", () => {
    const before = [field("a"), field("b")];
    const after = patchField(before, "b", { label: "Nowa", required: true });
    expect(before[1].label).toBe("b");
    expect(after[1]).toMatchObject({ label: "Nowa", required: true });
    expect(after[0]).toBe(before[0]);
    expect(fieldsPayload(after)[0]).not.toHaveProperty("source_label");
  });

  it("maps states to tones and labels", () => {
    expect(checkTone({ state: "ok" })).toBe("success");
    expect(checkTone({ state: "warn" })).toBe("warning");
    expect(checkTone({ state: "block" })).toBe("danger");
    expect(citeStateLabel("unverified")).toBe("do sprawdzenia");
    expect(isCustomTypeKey("custom:4")).toBe(true);
    expect(isCustomTypeKey("preliminary_cez")).toBe(false);
    expect(
      templateStatusLabel({
        withdrawn: false,
        active_version_no: 2,
        working_status: "pending",
        working_status_label: "do zatwierdzenia",
      }),
    ).toEqual({ label: "do zatwierdzenia", tone: "warning" });
    expect(
      templateStatusLabel({
        withdrawn: false,
        active_version_no: 2,
        working_status: null,
        working_status_label: null,
      }).label,
    ).toBe("zatwierdzony v2");
  });
});
