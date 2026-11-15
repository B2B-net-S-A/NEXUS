/** Fikcyjny zespół do testów panelu zespołu: zero prawdziwych osób i stawek. */
import type { PanelCandidate, PanelView } from "@/lib/api/clientPanel";
import type { TeamPanelView } from "@/lib/api/clientTeamPanel";

export function person(
  id: string,
  rate: string | null,
  available: string | null,
  extra: Partial<PanelCandidate> = {},
): PanelCandidate {
  return {
    public_id: id,
    name: `Osoba ${id}`,
    title: null,
    city: null,
    available_from: available,
    available_label: available == null ? "do ustalenia" : available <= "2026-11-15" ? "od zaraz" : `od ${available}`,
    available_confirmed_at: null,
    rate: rate == null ? null : { value: rate, unit: "hourly", currency: "PLN" },
    statuses: {},
    in_projects: 0,
    on_list: 0,
    missing: 0,
    sent_at: "2026-11-01",
    state: "none",
    ...extra,
  };
}

export function positionView(title: string, candidates: PanelCandidate[], showRate = true): PanelView {
  return {
    panel: { expires_at: "2027-01-14T23:59:59+01:00", show_rate: showRate, allow_actions: true, show_other_candidates: true },
    job: {
      title,
      reference: null,
      client_name: "Firma Testowa",
      request_text: null,
      added_at: "2026-11-01",
      work_mode: null,
      location: null,
      deadline: null,
    },
    owner: { name: "Opiekunka Testowa" },
    requirements: [],
    candidates,
  };
}

/** Dwa stanowiska: analityk (1 miejsce, 120 albo 140 zł/h), tester (2 miejsca, 100 zł/h). */
export function fictionalTeam(): TeamPanelView {
  return {
    team: {
      name: "Zespół testowy",
      client_name: "Firma Testowa",
      expires_at: "2027-01-14T23:59:59+01:00",
      owner: { name: "Opiekunka Testowa" },
    },
    hours_per_month: 168,
    positions: [
      {
        key: "aaaaaaaaaaaaaaaa",
        short: "Analityk",
        headcount: 1,
        view: positionView("Analityk", [person("a1", "140.00", "2026-11-01"), person("a2", "120.00", "2026-12-01")]),
      },
      {
        key: "bbbbbbbbbbbbbbbb",
        short: "Tester",
        headcount: 2,
        view: positionView("Tester", [
          person("t1", "100.00", "2026-11-01"),
          person("t2", "100.00", null),
          person("t3", "100.00", "2026-11-02"),
        ]),
      },
    ],
  };
}
