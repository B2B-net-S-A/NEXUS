/**
 * Dane fikcyjne harnessu `/preview/client-panel`: osoby, rekrutacja i PDF są
 * wymyślone, a oba transporty działają w pamięci, więc ekran nie wysyła żadnego
 * żądania. Zapisy zmieniają wyłącznie stan tego obiektu.
 */
import type { ClientPanelAdminTransport, ClientPanelSettings, ClientPanelRequestItem } from "@/lib/api/clientPanelAdmin";
import type {
  PanelCandidate,
  PanelCandidateDetail,
  PanelTransport,
  PanelView,
  RequirementStatus,
} from "@/lib/api/clientPanel";

const REQUIREMENTS = [
  ["python", "Python, 6+ lat"],
  ["web", "Rozwój aplikacji webowych"],
  ["async", "Asynchroniczność"],
  ["fastapi", "FastAPI"],
  ["cloud", "Technologie chmurowe"],
  ["micro", "Implementacja mikrousług"],
  ["ddd", "Technika DDD"],
  ["linux", "Linux"],
  ["git", "Git lub podobny"],
  ["gerrit", "Gerrit"],
  ["jenkins", "Jenkins"],
  ["jira", "Jira"],
  ["confluence", "Confluence"],
  ["english", "Język angielski"],
].map(([key, label]) => ({ key, label }));

const CV_LINES = [
  "Anna Przykladowa",
  "Python Developer",
  "",
  "Umiejetnosci: Python, FastAPI, Linux, Git, Jira, Confluence",
  "Jezyki: angielski B2",
  "Certyfikaty: Linux Administrator (kurs przykladowy)",
  "",
  "02.2020 - obecnie, Firma Przykladowa S.A.",
  "Stanowisko: Python Developer",
  "Zakres zadan:",
  "Rozwijala kod wedlug DDD i architektury heksagonalnej w istniejacej bazie kodu",
  "Zaprojektowala mikroserwis w FastAPI z publikacja zdarzen asynchronicznych",
  "Konfigurowala srodowiska w chmurze publicznej i obserwowalnosc uslug",
  "Rozwijala aplikacje webowe w Pythonie, przeglad kodu w Git",
  "",
  "12.2018 - 01.2020, Hurtownia Przykladowa Sp. z o.o.",
  "Stanowisko: Junior Developer",
  "Rozwoj aplikacji webowych w Pythonie i utrzymanie testow",
];

function escapePdfText(text: string): string {
  return text.replace(/[\\()]/g, (char) => `\\${char}`);
}

/** Najprostszy PDF z warstwą tekstu, żeby wyszukiwanie w podglądzie działało naprawdę. */
export function fictionalCvPdf(lines: readonly string[] = CV_LINES): Blob {
  const stream = [
    "BT /F1 12 Tf 56 780 Td 18 TL",
    ...lines.map((line) => `(${escapePdfText(line)}) Tj T*`),
    "ET",
  ].join("\n");
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 5 0 R /Resources << /Font << /F1 4 0 R >> >> >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
  ];
  let body = "%PDF-1.4\n";
  const offsets = objects.map((object, index) => {
    const offset = body.length;
    body += `${index + 1} 0 obj\n${object}\nendobj\n`;
    return offset;
  });
  const xrefStart = body.length;
  body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  body += offsets.map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`).join("");
  body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefStart}\n%%EOF\n`;
  return new Blob([body], { type: "application/pdf" });
}

const RATE = { value: "168.75", unit: "hourly", currency: "PLN" };

function statuses(project: string[], list: string[]): Record<string, RequirementStatus> {
  return Object.fromEntries(
    REQUIREMENTS.map(({ key }) => [
      key,
      project.includes(key) ? "project" : list.includes(key) ? "list" : "none",
    ]),
  );
}

function candidate(
  public_id: string,
  name: string,
  title: string,
  city: string,
  available_label: string,
  project: string[],
  list: string[],
  state: PanelCandidate["state"] = "none",
): PanelCandidate {
  return {
    public_id,
    name,
    title,
    city,
    available_from: null,
    available_label,
    available_confirmed_at: "2026-10-06",
    rate: RATE,
    statuses: statuses(project, list),
    in_projects: project.length,
    on_list: list.length,
    missing: REQUIREMENTS.length - project.length - list.length,
    sent_at: "2026-10-12",
    state,
  };
}

const CANDIDATES: PanelCandidate[] = [
  candidate(
    "fikc-anna",
    "Anna Przykładowa",
    "Python Developer",
    "Poznań",
    "od zaraz",
    ["python", "web", "async", "fastapi", "cloud", "micro", "ddd", "git"],
    ["linux", "english"],
  ),
  candidate(
    "fikc-jan",
    "Jan Testowy",
    "Python Backend Engineer",
    "Warszawa",
    "od 07.01.2027",
    ["python", "web", "fastapi", "cloud", "micro", "git"],
    ["jira"],
    "question_open",
  ),
  candidate(
    "fikc-maria",
    "Maria Fikcyjna",
    "Backend Engineer",
    "Warszawa",
    "od zaraz",
    ["python", "web", "fastapi", "linux", "micro"],
    ["git"],
    "interview_requested",
  ),
  candidate("fikc-piotr", "Piotr Demo", "Specjalista ds. CRM", "Kraków", "do ustalenia", ["cloud", "jira"], ["python", "english"], "not_fit"),
];

function evidenceFor(person: PanelCandidate): PanelCandidateDetail["evidence"] {
  return Object.fromEntries(
    REQUIREMENTS.map(({ key, label }) => {
      const status = person.statuses[key];
      if (status === "none") return [key, { status, items: [] }];
      const samples: Record<string, { quote: string; term: string }> = {
        ddd: {
          quote: "Rozwijala kod wedlug DDD i architektury heksagonalnej w istniejacej bazie kodu",
          term: "DDD",
        },
        fastapi: {
          quote: "Zaprojektowala mikroserwis w FastAPI z publikacja zdarzen asynchronicznych",
          term: "FastAPI",
        },
        // Fraza z polskimi znakami nie trafi w ten PDF, więc podgląd szuka samego słowa.
        linux: { quote: "Certyfikat: Linux Administrator", term: "Linux" },
      };
      const sample = samples[key] ?? { quote: `Praca z: ${label}`, term: label.split(/[\s,]+/)[0] };
      const items =
        status === "project"
          ? [{ kind: "project" as const, ...sample, where: "Firma Przykładowa S.A.", dates: "02.2020 - obecnie" }]
          : [{ kind: "list" as const, ...sample, where: null, dates: null }];
      return [key, { status, items }];
    }),
  );
}

function detailFor(person: PanelCandidate, withCv: boolean, withRate: boolean): PanelCandidateDetail {
  return {
    public_id: person.public_id,
    name: person.name,
    cv: withCv
      ? { available: true, filename: `ZOB-0001_${person.public_id}.pdf`, url: `#cv-${person.public_id}` }
      : { available: false, filename: null, url: null },
    evidence: evidenceFor(person),
    terms: {
      rate: withRate ? person.rate : null,
      available_label: person.available_label,
      available_confirmed_at: person.available_confirmed_at,
      city: person.city,
    },
    files:
      person.public_id === "fikc-anna"
        ? [{ id: 1, name: "Certyfikat przykładowy.pdf", kind: "certificate", url: "#plik-1" }]
        : [],
    thread:
      person.state === "question_open"
        ? [
            {
              id: 1,
              kind: "question",
              author: "Kasia",
              at: "2026-10-28T14:40:00Z",
              body: "Czy ma doświadczenie z chmurą publiczną?",
              answer: null,
              answered_at: null,
            },
          ]
        : [],
    interview:
      person.state === "interview_requested"
        ? {
            status: "awaiting_recruiter",
            slots: [
              { start: "2026-11-10T09:00:00Z", end: "2026-11-10T10:00:00Z", window_end: null },
              { start: "2026-11-12T10:00:00Z", end: "2026-11-12T11:00:00Z", window_end: null },
            ],
            chosen: null,
          }
        : { status: "none", slots: [], chosen: null },
  };
}

export interface FictionalPanelOptions {
  showRate?: boolean;
  allowActions?: boolean;
  showOthers?: boolean;
  withCv?: boolean;
}

export function fictionalPanelTransport({
  showRate = true,
  allowActions = true,
  showOthers = true,
  withCv = true,
}: FictionalPanelOptions = {}): PanelTransport {
  let people = CANDIDATES.map((person) => ({
    ...person,
    rate: showRate ? person.rate : null,
  }));
  const details = new Map(people.map((person) => [person.public_id, detailFor(person, withCv, showRate)]));
  const setState = (publicId: string, state: PanelCandidate["state"]) => {
    people = people.map((person) => (person.public_id === publicId ? { ...person, state } : person));
  };
  return {
    fetchPanel: async (publicId) => {
      const view: PanelView = {
        panel: {
          expires_at: "2026-12-11T00:00:00Z",
          show_rate: showRate,
          allow_actions: allowActions,
          show_other_candidates: showOthers,
        },
        job: {
          title: "Programista Python",
          reference: "ZOB-0001",
          client_name: "Bank Przykładowy",
          request_text:
            "Szukamy programisty Python do zespołu bankowości internetowej.\n\nWymagania:\n- Python, co najmniej 6 lat\n- rozwój aplikacji webowych, FastAPI, asynchroniczność\n- technologie chmurowe, mikrousługi, DDD\n- Linux, Git lub podobny, Gerrit, Jenkins, Jira, Confluence\n- język angielski w pracy z dokumentacją\n\nPraca hybrydowa w Warszawie, współpraca na ok. 12 miesięcy.",
          added_at: "2026-10-09",
          work_mode: "hybrid",
          location: "Warszawa",
          deadline: "2026-10-15",
        },
        owner: { name: "Olga Opiekunka" },
        requirements: REQUIREMENTS,
        candidates: showOthers
          ? people
          : people.filter((person) => person.public_id === publicId),
      };
      return view;
    },
    fetchCandidate: async (publicId) => {
      const detail = details.get(publicId);
      if (!detail) throw Object.assign(new Error("brak"), { response: { status: 404 } });
      return detail;
    },
    fetchCv: async () => fictionalCvPdf(),
    fileHref: (url) => url,
    sendQuestion: async (publicId, body) => {
      const detail = details.get(publicId);
      if (detail) {
        details.set(publicId, {
          ...detail,
          thread: [
            ...detail.thread,
            {
              id: detail.thread.length + 1,
              kind: "question",
              author: body.author_name,
              at: new Date().toISOString(),
              body: body.body,
              answer: null,
              answered_at: null,
            },
          ],
        });
      }
      setState(publicId, "question_open");
    },
    sendInterview: async (publicId, body) => {
      const detail = details.get(publicId);
      if (detail) {
        details.set(publicId, {
          ...detail,
          interview: {
            status: "awaiting_recruiter",
            slots: body.slots.map((slot) => ({ start: slot.start, end: null, window_end: null })),
            chosen: null,
          },
        });
      }
      setState(publicId, "interview_requested");
    },
    sendNotFit: async (publicId) => setState(publicId, "not_fit"),
    sendRequirementsChange: async () => undefined,
    sendEvent: () => undefined,
  };
}

const ADMIN_SETTINGS: ClientPanelSettings = {
  enabled: true,
  show_rate: true,
  show_other_candidates: true,
  allow_actions: true,
  expires_at: "2026-12-11T00:00:00Z",
  url: "https://nexus.example.test/k/FIKCYJNYLINK2345?c=fikc-anna",
  short_url: "nexus.example.test/k/FIKCYJNYLINK2345",
  candidates: [
    {
      candidate_id: 1,
      name: "Anna Przykładowa",
      public_id: "fikc-anna",
      hidden: false,
      in_projects: 8,
      on_list: 2,
      missing: 4,
      weak: [
        { key: "async", label: "Asynchroniczność", quote: "publikacja zdarzeń w projekcie", where: "Firma Przykładowa S.A." },
        { key: "linux", label: "Linux", quote: "tylko certyfikat", where: null },
      ],
      rejected_evidence: [],
    },
    {
      candidate_id: 2,
      name: "Jan Testowy",
      public_id: "fikc-jan",
      hidden: false,
      in_projects: 6,
      on_list: 1,
      missing: 7,
      weak: [{ key: "web", label: "Rozwój aplikacji webowych", quote: "słowo w opisie projektu", where: "Hurtownia Przykładowa" }],
      rejected_evidence: [],
    },
    {
      candidate_id: 4,
      name: "Piotr Demo",
      public_id: "fikc-piotr",
      hidden: true,
      in_projects: 2,
      on_list: 2,
      missing: 10,
      weak: [],
      rejected_evidence: [],
    },
  ],
  views: { total: 12, last_at: "2026-10-29T12:02:00Z", people: 2 },
  requests_open: 3,
  job_closed: false,
};

const ADMIN_REQUESTS: ClientPanelRequestItem[] = [
  {
    id: 1,
    kind: "interview",
    candidate_id: 1,
    candidate_name: "Anna Przykładowa",
    job_id: 1,
    job_title: "Programista Python",
    author_name: "Kasia",
    author_email: "kasia@bank-przykladowy.example",
    email_domain_known: true,
    body: null,
    reasons: null,
    slot_request_id: 71,
    status: "open",
    answer: null,
    created_at: "2026-11-02T09:12:00Z",
  },
  {
    id: 2,
    kind: "question",
    candidate_id: 2,
    candidate_name: "Jan Testowy",
    job_id: 1,
    job_title: "Programista Python",
    author_name: "Tomek",
    author_email: "tomek@poczta-prywatna.example",
    email_domain_known: false,
    body: "Czy ma doświadczenie z chmurą publiczną?",
    reasons: null,
    slot_request_id: null,
    status: "open",
    answer: null,
    created_at: "2026-10-28T14:40:00Z",
  },
  {
    id: 3,
    kind: "not_fit",
    candidate_id: 4,
    candidate_name: "Piotr Demo",
    job_id: 1,
    job_title: "Programista Python",
    author_name: "Kasia",
    author_email: "kasia@bank-przykladowy.example",
    email_domain_known: true,
    body: null,
    reasons: ["Brak kluczowej technologii"],
    slot_request_id: null,
    status: "open",
    answer: null,
    created_at: "2026-10-28T14:31:00Z",
  },
];

export function fictionalAdminTransport(
  initial: ClientPanelSettings = ADMIN_SETTINGS,
): ClientPanelAdminTransport {
  let settings = initial;
  let requests = ADMIN_REQUESTS;
  const removeRequest = (id: number) => {
    requests = requests.filter((item) => item.id !== id);
    settings = { ...settings, requests_open: requests.length };
  };
  return {
    fetchSettings: async () => settings,
    updateSettings: async (_jobId, patch) => {
      settings = { ...settings, ...patch };
    },
    rotateLink: async () => undefined,
    updatePerson: async (_jobId, candidateId, patch) => {
      settings = {
        ...settings,
        candidates: settings.candidates.map((person) =>
          person.candidate_id === candidateId
            ? {
                ...person,
                ...patch,
                weak: person.weak.filter((weak) => !patch.rejected_evidence?.includes(weak.key)),
              }
            : person,
        ),
      };
    },
    fetchRequests: async () => requests,
    answerRequest: async (id) => removeRequest(id),
    closeRequest: async (id) => removeRequest(id),
    fetchActivity: async () => [
      { at: "2026-10-29T12:02:00Z", action: "tab", detail: "Warunki", candidate_name: "Jan Testowy" },
      { at: "2026-10-27T08:16:00Z", action: "requirement", detail: "FastAPI", candidate_name: "Anna Przykładowa" },
      { at: "2026-10-27T08:14:00Z", action: "candidate", detail: null, candidate_name: "Anna Przykładowa" },
    ],
  };
}
