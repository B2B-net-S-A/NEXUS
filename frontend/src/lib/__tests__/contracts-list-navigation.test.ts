import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  buildContractDetailHref,
  buildClientContractRegisterUrl,
  buildContractorsListUrl,
  buildContractsListUrl,
  parseClientContractRegisterState,
  parseContractorsListState,
  parseContractsListState,
  parseContractsReturnContext,
  rememberContractsListScroll,
  restoreContractsListScroll,
  safeContractsReturnTarget,
  takeContractsListScroll,
} from "@/lib/contracts-list-navigation";

describe("contracts list navigation state", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    window.history.replaceState({}, "", "/contracts");
  });

  it("treats queryless /contracts as a fresh Active session", () => {
    expect(parseContractsListState("")).toEqual({
      explicit: false,
      state: {
        search: "",
        statusFilter: ["active"],
        typeFilter: [],
        endingSoon: false,
        page: 1,
      },
    });
  });

  it("round-trips filters, page and an intentionally cleared status", () => {
    const url = buildContractsListUrl({
      search: "Nordea Warszawa",
      statusFilter: [],
      typeFilter: ["b2b", "uop"],
      endingSoon: true,
      page: 3,
    });

    expect(url).toBe(
      "/contracts?status=all&contract_type=b2b&contract_type=uop&q=Nordea+Warszawa&ending=30&page=3",
    );
    expect(parseContractsListState(url.split("?")[1] ?? "")).toMatchObject({
      explicit: true,
      state: {
        search: "Nordea Warszawa",
        statusFilter: [],
        typeFilter: ["b2b", "uop"],
        endingSoon: true,
        page: 3,
      },
    });
  });

  it("embeds a validated return target in contract links", () => {
    const returnTarget = "/contracts?status=draft&contract_type=b2b&page=2";
    const href = buildContractDetailHref(563, returnTarget);
    const detailQuery = href.slice(href.indexOf("?"));

    expect(href).toContain("/contracts/563?from=contracts");
    expect(parseContractsReturnContext(detailQuery)).toEqual({
      fromContracts: true,
      hasReturnTarget: true,
      returnTarget,
    });
  });

  it("rejects external and non-list return targets", () => {
    expect(safeContractsReturnTarget("//evil.example/contracts")).toBe(
      "/contracts",
    );
    expect(safeContractsReturnTarget("/contracts/563?status=draft")).toBe(
      "/contracts",
    );
    expect(
      parseContractsReturnContext(
        "?from=contracts&returnTo=https%3A%2F%2Fevil.example%2Fcontracts",
      ),
    ).toEqual({
      fromContracts: true,
      hasReturnTarget: false,
      returnTarget: "/contracts",
    });
  });

  it("round-trips the operations tab/page and drops uncontrolled query params", () => {
    const returnTarget = buildContractorsListUrl({ tab: "ending", page: 4 });
    expect(returnTarget).toBe(
      "/contracts?view=operations&tab=ending&contractors_page=4",
    );
    expect(parseContractorsListState(returnTarget.split("?")[1] ?? "").state).toEqual({
      tab: "ending",
      page: 4,
    });
    expect(
      safeContractsReturnTarget(`${returnTarget}&redirect=https://evil.example`),
    ).toBe(returnTarget);

    const detailHref = buildContractDetailHref(
      91,
      returnTarget,
      "contractors",
    );
    expect(parseContractsReturnContext(detailHref.split("?")[1] ?? "")).toEqual({
      fromContracts: false,
      hasReturnTarget: true,
      returnTarget,
    });
  });

  it("does not interpret the global page/filter as operations state", () => {
    const mixedViewUrl =
      "/contracts?view=operations&tab=ending&page=9&status=draft&contract_type=b2b";

    expect(parseContractorsListState(mixedViewUrl.split("?")[1] ?? "")).toEqual({
      explicit: true,
      state: { tab: "ending", page: 1 },
    });
    expect(safeContractsReturnTarget(mixedViewUrl)).toBe(
      "/contracts?view=operations&tab=ending",
    );
  });

  it("round-trips a client register with all local filters and page", () => {
    const state = {
      search: "Kowalski",
      statusFilter: ["active", "ending"] as const,
      periodFrom: "2026-01-01",
      periodTo: "2026-12-31",
      subcategoryFilter: ["Backend", "Data"],
      page: 3,
    };
    const returnTarget = buildClientContractRegisterUrl(
      42,
      "Nordea Bank",
      { ...state, statusFilter: [...state.statusFilter] },
    );
    expect(parseClientContractRegisterState(returnTarget.split("?")[1] ?? "").state)
      .toEqual({ ...state, statusFilter: [...state.statusFilter] });
    expect(safeContractsReturnTarget(`${returnTarget}&javascript=alert(1)`)).toBe(
      returnTarget,
    );
    expect(
      parseContractsReturnContext(
        new URL(buildContractDetailHref(563, returnTarget, "client-register"), "https://nexus.invalid").search,
      ),
    ).toMatchObject({ hasReturnTarget: true, returnTarget });
  });

  it("stores scroll as a one-shot snapshot for the exact return URL", () => {
    const main = document.createElement("main");
    main.id = "main";
    main.scrollTop = 740;
    document.body.appendChild(main);
    const returnTarget = "/contracts?status=draft&page=4";

    rememberContractsListScroll(returnTarget);

    expect(takeContractsListScroll(returnTarget)).toBe(740);
    expect(takeContractsListScroll(returnTarget)).toBeNull();

    restoreContractsListScroll(320);
    expect(main.scrollTop).toBe(320);
    main.remove();
  });
});
