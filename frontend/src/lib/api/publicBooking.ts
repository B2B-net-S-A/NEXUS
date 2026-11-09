/**
 * Wybór terminu z maila (`/t/{token}`) — lustro `/api/public/own-hiring/{token}`.
 * Goły axios: instancja z `@/lib/api` dokleja token i przy 401 wyrzuca na logowanie.
 */
import axios from "axios";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://api.nexus.dynaminds.pl";

export interface PublicSlotDay {
  date: string;
  label: string;
  slots: string[];
}

export interface PublicBookingView {
  state: "open" | "booked" | "finished" | "closed";
  role_title: string;
  owner_name: string;
  minutes: number;
  calendar_available: boolean;
  days: PublicSlotDay[];
  booking: { start: string; end: string; join_url: string | null } | null;
}

const url = (token: string, suffix = "") =>
  `${API_BASE}/api/public/own-hiring/${encodeURIComponent(token)}${suffix}`;

export const publicBookingApi = {
  view: async (token: string) => (await axios.get<PublicBookingView>(url(token))).data,
  book: async (token: string, start: string) =>
    (await axios.post<PublicBookingView>(url(token, "/book"), { start })).data,
  cancel: async (token: string) =>
    (await axios.post<PublicBookingView>(url(token, "/cancel"))).data,
  noFit: async (token: string, note: string) =>
    (await axios.post<PublicBookingView>(url(token, "/no-fit"), { note })).data,
  withdraw: async (token: string) =>
    (await axios.post<PublicBookingView>(url(token, "/withdraw"))).data,
};
