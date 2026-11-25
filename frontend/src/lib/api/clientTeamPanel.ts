/**
 * Publiczny panel klienta dla zespołu (`/k/z/{token}`) — lustro
 * `/api/public/team-panel/{token}`.
 *
 * Jak `clientPanel.ts`: goły axios, bez `@/lib/api`, bo klient z linku nie ma
 * konta, a tamta instancja dokleja sesję pracownika. Szczegóły stanowiska idą
 * przez `httpPanelTransport(position.key)`: klucz stanowiska to token jego panelu.
 */
import axios from "axios";

import type { PanelAuthor, PanelView } from "./clientPanel";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://api.nexus.b2bnetwork.pl";

export interface TeamPanelPosition {
  /** Token panelu stanowiska; otwiera `/api/public/panel/{key}`. */
  key: string;
  short: string;
  headcount: number;
  view: PanelView;
  /** Szacunek stawki (zł/h) dla stanowiska jeszcze bez stawek w CV; tylko przy pokazywanych stawkach. */
  estimate?: { min: number; max: number } | null;
}

export interface TeamPanelView {
  team: {
    name: string;
    client_name: string | null;
    expires_at: string | null;
    owner: { name: string | null } | null;
  };
  hours_per_month: number;
  positions: TeamPanelPosition[];
  /** Gotowe składy zatwierdzone przez opiekuna: `{<klucz stanowiska>: [public_id]}`. */
  variants?: TeamPanelVariant[];
}

export interface TeamPanelVariant {
  key: string;
  name: string;
  why: string;
  picks: Record<string, string[]>;
}

export interface TeamInterviewsBody extends PanelAuthor {
  duration_minutes: number;
  slots: { start: string }[];
  interviewers?: string;
  prep_note?: string;
  picks: Record<string, string[]>;
}

export interface TeamInterviewsResult {
  created: number;
  skipped: { key: string; public_id: string; reason: string }[];
}

export interface TeamSelectionBody extends PanelAuthor {
  /** `{<klucz stanowiska>: [public_id, …]}` */
  picks: Record<string, string[]>;
  note?: string;
}

export interface TeamPanelTransport {
  fetchTeam: () => Promise<TeamPanelView>;
  sendSelection: (body: TeamSelectionBody) => Promise<void>;
  sendInterviews: (body: TeamInterviewsBody) => Promise<TeamInterviewsResult>;
}

export function httpTeamPanelTransport(token: string): TeamPanelTransport {
  const base = `${API_BASE}/api/public/team-panel/${encodeURIComponent(token)}`;
  return {
    fetchTeam: () => axios.get<TeamPanelView>(base).then((r) => r.data),
    sendSelection: (body) => axios.post(`${base}/selection`, body).then(() => undefined),
    sendInterviews: (body) =>
      axios.post<TeamInterviewsResult>(`${base}/interviews`, body).then((r) => r.data),
  };
}

export function teamPanelKey(token: string) {
  return ["client-team-panel", token] as const;
}
