// Local demonstration only. Uses the production renderers with fictional data.
// No Chrome API, credentials, live LinkedIn page or NEXUS API is involved.
import { initialAddState, renderAdd } from "../src/panel/screen-add.js";
import { initialPersonState, renderPerson } from "../src/panel/screen-person.js";
import { readPageDom } from "../src/readers/index.js";

const fixture = await (await fetch("fixtures/profile-public.html")).text();
const read = readPageDom(new DOMParser().parseFromString(fixture, "text/html"), "https://www.linkedin.com/in/zofia-testowa-123/");
const lookup = {
  status: "found",
  candidate: { id: 1, name: "Zofia Testowa", headline: "Senior Java Developer", city: "Kraków", url: "https://nexus.example.test/candidates/1", in_nexus_since: "2024-03-02" },
  owner: { user_id: 85, name: "Katarzyna", is_me: false, last_contact_at: "2026-10-01T10:00:00Z" },
  processes: [{ job_id: 11, job_title: "Java Developer", client_name: "Klient Testowy", stage_label: "Screening", recruiter_name: "Katarzyna", closed: false }],
  contacts: [{ at: "2026-10-01T10:00:00Z", user_name: "Katarzyna", channel_label: "telefon", note: "Chętnie pozna szczegóły nowego projektu." }],
  rate: { label: "150 zł/h B2B", as_of: "2026-10-01" },
  rodo: { status: "valid", label: "zgoda do 03.2027" },
  off_limits: null, contractor: null, job_change: null, ambiguous: [], matches: [],
};
const state = {
  me: { user: { id: 26, name: "Malwina Testowa", initials: "MT" }, usage: { reads_today: 34, reads_limit: 150 } },
  read, lookup, add: initialAddState(read), person: initialPersonState(),
  tab: { id: 1, url: read.profile.page_url }, page: { kind: "profile", key: "in/zofia-testowa-123" },
};
const api = new Proxy({}, { get: () => async () => { throw new Error("Demonstracja nie łączy się z API."); } });
const mode = new URLSearchParams(location.search).get("screen") || "person";
const copies = {
  person: ["Sprawdź osobę, zanim napiszesz", "Zobacz historię kontaktów i aktywne rekrutacje zespołu w jednym panelu.", ["Rozpoznaj osobę w bazie NEXUSA", "Sprawdź, kto ją prowadzi", "Zapisz kontakt lub notatkę"]],
  add: ["Od profilu do rekrutacji", "Sprawdź odczytane dane, popraw je i wybierz rekrutacje przed zapisaniem osoby.", ["Dane widoczne na otwartej stronie", "Dopasowania do rekrutacji", "Zapis dopiero po Twoim kliknięciu"]],
  message: ["Przygotuj wiadomość z kontekstem", "Wybierz rekrutację, edytuj szkic i skopiuj tekst. Wiadomość wysyłasz samodzielnie.", ["Szkic dla wybranej rekrutacji", "Pełna kontrola nad treścią", "Zapis kontaktu i przypomnienie"]],
};
const [title, lead, benefits] = copies[mode];
document.getElementById("title").textContent = title;
document.getElementById("lead").textContent = lead;
for (const [index, text] of benefits.entries()) {
  const row = document.createElement("div");
  const number = document.createElement("span"); number.className = "number"; number.textContent = index + 1;
  row.append(number, text); document.getElementById("benefits").append(row);
}
if (mode === "add") {
  state.lookup = { ...lookup, status: "not_found", candidate: null, owner: null, processes: [], contacts: [], matches: [
    { job_id: 11, title: "Java Developer", client_name: "Klient Testowy", recruiter_name: "Katarzyna", score: 81 },
    { job_id: 12, title: "Kotlin Developer", client_name: "Inny Klient", recruiter_name: "Igor", score: 55 },
  ] };
  state.add.selected.add(11);
}
if (mode === "message") {
  state.person.tab = "message";
  state.person.message = {
    job: { id: 11, title: "Java Developer", client_name: "Klient Testowy" }, kind: "inmail",
    text: "Cześć Zofio,\n\nprowadzę rekrutację Java Developer dla Klienta Testowego. Twoje doświadczenie w Javie i Spring Boot pasuje do potrzeb zespołu.\n\nPorozmawiamy o projekcie?\n\nPozdrawiam,\nMalwina",
    ai: true, busy: false, error: null, notice: null, remind: "3", requested: true,
  };
}
const ctx = { state, api, render: () => document.getElementById("view").replaceChildren(mode === "add" ? renderAdd(ctx) : renderPerson(ctx)), onWrite() {}, refreshLookup() {}, addLocalContact() {} };
ctx.render();
document.documentElement.dataset.ready = "true";
