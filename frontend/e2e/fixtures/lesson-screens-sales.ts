/**
 * Fikcyjne odpowiedzi ekranów lekcji nowości — obszar: sales.
 * Zasady jak w `lesson-screens.ts`: dane wymyślone (repo publiczne), typy z aplikacji,
 * klucz = ścieżka API bez query.
 *
 * Sprzedaż nie jest w zestawie Poligonu (`OWNED_PATHS` w `src/lib/poligon/store.ts`),
 * więc na produkcji lekcja czyta prawdziwe `/api/sales/*`. Tu tyle danych, ile trzeba,
 * żeby stanęły elementy z pokazu i element z zadania.
 *
 * Identyfikatory siedmiocyfrowe (9 906 xxx), nie 990000–999999: sześciocyfrowy numer
 * z tego zakresu w adresie (`/api/sales/calling/records/…`) Poligon bierze za swój
 * (`mentionsPoligon` w `src/lib/poligon/store.ts`) i odpowiada „Nie znaleziono” bez sieci.
 */
import type {
  LeadList,
  MyDay,
  Offers,
  OfferSectionTotals,
  Pipeline,
  Ref,
  SalesCompany,
  SalesCompanyList,
} from "../../src/lib/api/sales";
import type { BotQuestions } from "../../src/lib/api/sales-bot";
import type { BotPeopleList } from "../../src/lib/api/sales-bot-people";
import type {
  CallCampaign,
  CallCard,
  CallQueue,
  CallRecordTable,
  DayCounts,
  QueueItem,
} from "../../src/lib/api/sales-calling";

const TODAY = "2026-11-26";

const COMPANY: Ref = { id: 9906001, name: "Hurtownia Przykładowa Sp. z o.o." };
const CAMPAIGN: Ref = { id: 9906011, name: "Kampania testowa: zespoły IT" };

const ZERO_DAY: DayCounts = { calls: 0, talks: 0, offers: 0, meetings: 0 };

/** Rekord kampanii (nad nazwą firmy „Kampania: …”): „Umówione spotkanie” otwiera formularz z zaproszeniem Teams. */
const QUEUE_ITEM: QueueItem = {
  key: "record-9906021",
  section: "new",
  record_id: 9906021,
  opportunity_id: null,
  opportunity_title: null,
  company: COMPANY,
  campaign: CAMPAIGN,
  person_name: "Jan Testowy",
  person_title: "Kierownik IT",
  phone: null,
  state: "new",
  due_on: null,
  attempts: 0,
  last_outcome_at: null,
  since: "2026-11-24",
  callback_reason: null,
};

const CALL_QUEUE: CallQueue = {
  today: TODAY,
  counts: { callbacks: 0, no_answer: 0, meetings: 0, new: 1, later: 0 },
  callbacks: [],
  no_answer: [],
  meetings: [],
  new: [QUEUE_ITEM],
  campaigns: [CAMPAIGN],
  today_counts: ZERO_DAY,
  yesterday: "2026-11-25",
  yesterday_counts: ZERO_DAY,
  callers: [],
};

/** Tabela Dzwonienia (lekcja „kilka rekordów naraz”): ten sam rekord kampanii co w kolejce. */
const CALL_RECORDS: CallRecordTable = {
  items: [QUEUE_ITEM],
  total: 1,
  counts: { new: 1 },
  callers: [],
  repeats: 0,
};

const CALL_CARD: CallCard = {
  company: COMPANY,
  domain: null,
  contact_id: null,
  email: null,
  contact_source: null,
  note: null,
  service: null,
  script: null,
  linkedin_url: null,
  do_not_contact: false,
  client_refusal: null,
  can_save: true,
  history: [],
  earlier_calls: [],
  crm_opportunity: null,
};

const CAMPAIGNS: CallCampaign[] = [
  {
    id: CAMPAIGN.id,
    name: CAMPAIGN.name,
    service: null,
    script: null,
    total: 1,
    counts: { new: 1 },
  },
];

/** Lejek „sales” z etapem „Spotkanie kwalifikujące”: bez niego „Umówione spotkanie” jest wyłączone. */
const PIPELINES: Pipeline[] = [
  {
    id: 9906031,
    key: "sales",
    name: "Sprzedaż",
    is_default: true,
    stages: [
      {
        id: 9906032,
        key: "qualifying-meeting",
        name: "Spotkanie kwalifikujące",
        position: 1,
        probability: 20,
        outcome: "open",
        qualifies: true,
        color: null,
      },
    ],
  },
];

/** Kartoteka: jedna firma, jej karta i pytania do bota (pole „Zapytaj bota” stoi w Przeglądzie). */
const SALES_COMPANY: SalesCompany = {
  id: COMPANY.id,
  name: COMPANY.name,
  legal_name: null,
  nip: null,
  krs: null,
  regon: null,
  domain: null,
  website_url: null,
  linkedin_url: null,
  industry: "Handel hurtowy",
  size_range: null,
  hq_city: "Poznań",
  hq_country: "PL",
  description: null,
  lifecycle_stage: "prospect",
  tier: null,
  status: "active",
  tags: [],
  source: null,
  parent: null,
  client: null,
  owner: null,
  owner_label: null,
  needs_review: false,
  open_opportunities: 0,
  open_value: "0",
  archived_at: null,
  created_at: "2026-11-02T08:00:00+00:00",
  updated_at: "2026-11-20T08:00:00+00:00",
};

const COMPANIES: SalesCompanyList = { items: [SALES_COMPANY], total: 1 };

const QUESTIONS: BotQuestions = { enabled: true, items: [] };

/**
 * Leady: pusta lista z włączonymi zadaniami bota — wtedy przełącznik ma „Warto wrócić”,
 * „Nowe centra IT” i (z edycją Sprzedaży) „Lista z researchu”.
 */
const LEADS: LeadList = {
  items: [],
  total: 0,
  counts: { new: 0, contacted: 0, converted: 0, dismissed: 0 },
  signals_enabled: false,
  bot_tasks_enabled: true,
};

/** „Osoby od bota” w liście z researchu: sekcja stoi także bez wyników do przeglądu. */
const BOT_PEOPLE: BotPeopleList = {
  enabled: true,
  items: [],
  running_company_ids: [],
};

/** Mój dzień: jedno zaległe zadanie, przy nim „Zaplanuj” z polem własnej daty. */
const MY_DAY: MyDay = {
  today: TODAY,
  counts: { meetings: 0, reply: 0, overdue: 1, offers: 0, older_tasks: 0 },
  meetings: [],
  reply: [],
  overdue: [
    {
      key: "task-9906041",
      section: "overdue",
      company: COMPANY,
      opportunity: null,
      activity_id: 9906041,
      kind: "task",
      subject: "Zadzwonić w sprawie zespołu testerów",
      at: "2026-11-24T09:00:00+00:00",
      days: 2,
      amount: null,
      currency: "PLN",
      open_opportunities: 0,
      duration_minutes: null,
      web_link: null,
      do_not_contact: false,
      person: null,
      people_without_phone: [],
    },
  ],
  offers: [],
  prep: null,
  signals: [],
};

const NO_OFFERS: OfferSectionTotals = { count: 0, mrr: "0" };
const ONE_TO_DECIDE: Record<"in_progress" | "to_decide", OfferSectionTotals> = {
  in_progress: NO_OFFERS,
  to_decide: { count: 1, mrr: "12000" },
};

/** Oferty: jedna pozycja „Do decyzji” z punktem od bota. */
const OFFERS: Offers = {
  scope: "all",
  items: [
    {
      id: 9906051,
      title: "Zespół testerów dla hurtowni",
      company: COMPANY,
      pipeline_id: PIPELINES[0].id,
      pipeline_name: PIPELINES[0].name,
      stage: { id: 9906052, key: "offer", name: "Oferta" },
      is_offer: true,
      owner: { id: 9906053, name: "Jan Testowy" },
      owner_in_sales: true,
      mrr_value: "12000",
      currency: "PLN",
      idle_since: "2026-10-20",
      idle_days: 37,
      expected_close_date: null,
      close_overdue: false,
      keep_open_until: null,
      postponed: false,
      section: "to_decide",
      reason: "idle",
      step: null,
      bot_points: {
        generated_at: "2026-11-23T06:00:00+00:00",
        points: [
          {
            text: "Firma zapowiedziała nowy magazyn i dział IT.",
            url: null,
            published: "2026-11-18",
          },
        ],
      },
    },
  ],
  totals: {
    mine: { in_progress: NO_OFFERS, to_decide: NO_OFFERS },
    unowned: { in_progress: NO_OFFERS, to_decide: NO_OFFERS },
    all: ONE_TO_DECIDE,
  },
};

export const SCREENS_SALES: Record<string, unknown> = {
  "/api/sales/pipelines": PIPELINES,
  "/api/sales/calling/queue": CALL_QUEUE,
  "/api/sales/calling/campaigns": CAMPAIGNS,
  "/api/sales/calling/records": CALL_RECORDS,
  [`/api/sales/calling/records/${QUEUE_ITEM.record_id}`]: CALL_CARD,
  "/api/sales/companies": COMPANIES,
  [`/api/sales/companies/${COMPANY.id}`]: SALES_COMPANY,
  [`/api/sales/companies/${COMPANY.id}/questions`]: QUESTIONS,
  "/api/sales/leads": LEADS,
  "/api/sales/bot-people/pending": BOT_PEOPLE,
  "/api/sales/my-day": MY_DAY,
  "/api/sales/offers": OFFERS,
};
