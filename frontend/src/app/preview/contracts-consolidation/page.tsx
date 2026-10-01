"use client";

/**
 * Harness wizualny konsolidacji kontraktorów wieloklientowych — bez API i bez
 * logowania (wzorzec `preview/dl-alerts`): produkcyjne komponenty + ZASIANY
 * cache react-query, żeby żaden `queryFn` nigdy nie wystartował (niezasiany
 * klucz → 401 → redirect na /login, patrz pamięć projektu).
 *
 * Pokazuje obok siebie:
 * 1. Zgrupowaną listę kontraktów (jedna osoba × N klientów w jednym wierszu,
 *    kolumny „Stawka kosztowa"/„Stawka przychodowa", rozbicie per klient),
 * 2. Dialog „+ Dodaj kolejny projekt" (walidacja: klient wymagany).
 *
 * Auth: zustand store dostaje admina z view_finance — komponenty czytają rolę
 * z tego samego store'a co produkcja, więc kolumny finansowe się renderują.
 *
 * 3. Boczny panel kontraktu (wersja B, 29.09.2026) — klik w wiersz albo
 *    `?contract=<id>` w adresie otwiera go od razu (np. `?contract=467` —
 *    kontrakt zakończony z „Cofnij zakończenie”, `?contract=300` — brak
 *    aktywnego zamówienia). Szczegóły, dokumenty i historia każdego kontraktu
 *    z listy są zasiane.
 *
 * UWAGA: harness gwarantuje zero requestów — wszystkie zapytania są zasiane,
 * a interceptor axios odrzuca każde żądanie, które mimo to by wyszło (okna
 * otwierane z panelu pytają o klucze nie do zasiania). Zapisy blokuje też
 * layout `/preview`.
 */

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ContractsListV2 } from "@/components/v2/pages/ContractsListV2";
import { ContractsClientPicker } from "@/components/contracts/ContractsClientPicker";
import { WorkspaceModeTabs } from "@/components/ds/WorkspaceModeTabs";
import { AddProjectDialog } from "@/components/contracts/AddProjectDialog";
import { ToastProvider } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/store/auth";
import { DEFAULT_CONTRACT_STATUS_FILTER } from "@/lib/contracts-list-navigation";

const member = (over: Record<string, unknown>) => ({
  client_name: null,
  job_title: null,
  start_date: "2026-07-01",
  end_date: "2026-09-30",
  latest_order_end_date: null,
  contract_type: "b2b",
  rate_candidate: 135,
  rate_client: 185,
  margin: 50,
  rate_unit: "hourly",
  currency: "PLN",
  status: "active",
  ...over,
});

const LIST_PAYLOAD = {
  items: [
    {
      id: 467,
      candidate_id: 10,
      candidate_name: "Paweł Makietowy",
      client_name: "Bank Sigma",
      job_title: null,
      status: "ended",
      contract_type: "b2b",
      start_date: "2026-07-01",
      end_date: "2026-09-30",
      rate_candidate: 135,
      rate_client: 185,
      margin: 50,
      currency: "PLN",
      group_members: [
        member({
          id: 512,
          client_id: 2,
          client_name: "Bank Omega",
          rate_candidate: 128,
          rate_client: 171.5,
          margin: 42.5,
          end_date: null,
          job_title: "Tester Mobile",
        }),
        member({
          id: 467,
          client_id: 1,
          client_name: "Bank Sigma",
          status: "ended",
        }),
      ],
    },
    {
      id: 300,
      candidate_id: 11,
      candidate_name: "Jakub Testowy",
      client_name: "UBEZPIECZENIA SIGMA - ODDZIAŁ W POLSCE",
      job_title: "Tester Mobile",
      status: "active",
      contract_type: "b2b",
      start_date: "2026-04-27",
      end_date: "2026-12-31",
      rate_candidate: 105,
      rate_client: 148,
      margin: 40,
      currency: "PLN",
      group_members: [
        member({
          id: 300,
          client_id: 3,
          client_name: "UBEZPIECZENIA SIGMA - ODDZIAŁ W POLSCE",
          rate_candidate: 105,
          rate_client: 148,
          margin: 40,
          job_title: "Tester Mobile",
        }),
      ],
    },
    // Przykład z ticketu synchronizacji kontrakt ↔ zamówienia (09.2026):
    // umowa z generatora (122,50 zł/h) po uzupełnieniu zamówienia 1360 PLN/MD —
    // aktywna, w MD, z osobnym okresem zamówienia pod okresem umowy.
    {
      id: 650,
      candidate_id: 12,
      candidate_name: "Bartosz Próbny",
      client_name: "Bank Lambda S.A.",
      job_title: "Analityk Biznesowy - zastępstwo za: Wiktoria Testowa",
      status: "active",
      contract_type: "b2b",
      start_date: "2026-09-14",
      end_date: null,
      client_order_start_date: "2026-09-15",
      client_order_end_date: "2026-12-31",
      rate_candidate: 980,
      rate_client: 1360,
      margin: 380,
      rate_unit: "daily",
      currency: "PLN",
      group_members: [
        member({
          id: 650,
          client_id: 4,
          client_name: "Bank Lambda S.A.",
          job_title: "Analityk Biznesowy - zastępstwo za: Wiktoria Testowa",
          start_date: "2026-09-14",
          end_date: null,
          client_order_start_date: "2026-09-15",
          client_order_end_date: "2026-12-31",
          rate_candidate: 980,
          rate_client: 1360,
          margin: 380,
          rate_unit: "daily",
        }),
      ],
    },
    // Audyt 24.09.2026 (U5): umowa „Aktywna", która dopiero się zacznie —
    // wiersz niesie „startuje DD.MM", a nagłówek liczy ją osobno.
    {
      id: 651,
      candidate_id: 13,
      candidate_name: "Ewa Przyszła",
      client_name: "Bank Omega",
      job_title: "Tester Mobile",
      status: "active",
      contract_type: "b2b",
      start_date: "2031-10-01",
      end_date: null,
      rate_candidate: 115,
      rate_client: 158,
      margin: 40,
      rate_unit: "hourly",
      currency: "PLN",
      group_members: [
        member({
          id: 651,
          client_id: 2,
          client_name: "Bank Omega",
          job_title: "Tester Mobile",
          start_date: "2031-10-01",
          end_date: null,
          rate_candidate: 115,
          rate_client: 158,
          margin: 40,
        }),
      ],
    },
  ],
  total: 4,
  future_start_total: 1,
  page: 1,
  page_size: 20,
};

type ListItem = (typeof LIST_PAYLOAD.items)[number];
type ListMember = ReturnType<typeof member> & {
  id: number;
  client_id: number;
  client_name: string | null;
  job_title?: string | null;
  client_order_start_date?: string;
  client_order_end_date?: string;
};

/** Szczegóły kontraktu z panelu — lustro odpowiedzi `GET /api/contracts/{id}`. */
function contractDetail(item: ListItem, m: ListMember) {
  const siblings = (item.group_members as ListMember[]).filter(
    (other) => other.id !== m.id,
  );
  const status = String(m.status ?? item.status);
  return {
    id: m.id,
    candidate_id: item.candidate_id,
    client_id: m.client_id,
    job_id: null,
    candidate_name: item.candidate_name,
    client_name: m.client_name,
    job_title: m.job_title ?? null,
    candidate_email_effective: "kontakt@example.com",
    candidate_phone_effective: "+48 600 100 200",
    candidate_email_source: "candidate_profile",
    candidate_phone_source: "contract",
    start_date: m.start_date,
    end_date: m.end_date ?? null,
    client_order_start_date: m.client_order_start_date ?? null,
    client_order_end_date: m.client_order_end_date ?? null,
    rate_candidate: m.rate_candidate,
    rate_client: m.rate_client,
    margin: m.margin,
    monthly_margin: typeof m.margin === "number" ? m.margin * 168 : null,
    rate_unit: m.rate_unit ?? "hourly",
    billing_hours_per_month: 168,
    currency: "PLN",
    rate_client_currency: "PLN",
    rate_candidate_currency: "PLN",
    contract_type: m.contract_type,
    status,
    work_mode: "remote",
    notice_period_months: 1,
    termination_reason: status === "ended" ? "project_ended" : null,
    terminated_at: status === "ended" ? m.end_date : null,
    can_reverse_termination: status === "ended",
    can_return_after_break: status === "ended",
    related_contracts: siblings.map((other) => ({
      id: other.id,
      client_id: other.client_id,
      client_name: other.client_name,
      status: other.status,
      contract_type: other.contract_type,
      start_date: other.start_date,
      end_date: other.end_date ?? null,
    })),
  };
}

const PANEL_DOCUMENTS = [
  {
    id: 9001,
    filename: "Umowa-B2B-przyklad.pdf",
    doc_type: "contract",
    content_type: "application/pdf",
    size_bytes: 120_000,
    expiry_date: null,
    uploaded_by: 1,
    uploaded_by_email: "preview@example.com",
    created_at: "2026-07-01T09:00:00Z",
    source: "sharepoint_import",
  },
  {
    id: 9002,
    filename: "Zamowienie-przyklad.pdf",
    doc_type: "order",
    content_type: "application/pdf",
    size_bytes: 80_000,
    expiry_date: null,
    uploaded_by: 1,
    uploaded_by_email: "preview@example.com",
    created_at: "2026-09-15T09:00:00Z",
    sharepoint_item_id: "fikcyjny-element",
  },
];

const PANEL_ACTIVITIES = [
  { id: 1, action: "status_changed", details: null, user_id: 1, user_name: "Preview Admin", created_at: "2026-09-20T10:00:00Z" },
  { id: 2, action: "updated", details: null, user_id: 1, user_name: "Preview Admin", created_at: "2026-09-10T10:00:00Z" },
  { id: 3, action: "created", details: null, user_id: 1, user_name: "Preview Admin", created_at: "2026-07-01T10:00:00Z" },
];

function seededClient(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: Infinity,
        retry: false,
        refetchOnMount: false,
        refetchOnWindowFocus: false,
      },
    },
  });
  // Klucz MUSI odpowiadać temu z komponentu (debouncedSearch="", filtry puste,
  // endingSoon=false, page=1) — inaczej queryFn wystartuje i strzeli w API.
  // Domyślny filtr statusów rejestru to „Aktywne + Kończące się"
  // (`DEFAULT_CONTRACT_STATUS_FILTER`) — klucz musi go nieść.
  // Pusty zakres dat i brak sortowania też są częścią klucza.
  qc.setQueryData(
    [
      "contracts-v2",
      "",
      DEFAULT_CONTRACT_STATUS_FILTER,
      [],
      false,
      { startFrom: "", startTo: "", orderEndFrom: "", orderEndTo: "" },
      { by: null, dir: "asc" },
      1,
    ],
    LIST_PAYLOAD,
  );
  qc.setQueryData(["contracts-expiring-v2"], []);
  // Boczny panel: szczegóły, dokumenty i historia KAŻDEGO kontraktu z listy
  // (te same klucze co karta kontraktu).
  for (const item of LIST_PAYLOAD.items) {
    for (const m of item.group_members as ListMember[]) {
      qc.setQueryData(["contract", m.id], contractDetail(item, m));
      qc.setQueryData(["contract-documents", m.id], PANEL_DOCUMENTS);
      qc.setQueryData(["contract-activities", m.id], PANEL_ACTIVITIES);
    }
  }
  // Klucz MUSI być pełny: `AddProjectDialog` pyta o klientów zdatnych do
  // kontraktu (`["clients-lookup-add-project", "contract-eligible"]`).
  // Harness zasiewał wersję JEDNOELEMENTOWĄ sprzed dołożenia tego filtra, więc
  // `queryFn` startował, dostawał 401 i przerzucał na /login — dokładnie to,
  // czemu zasiewanie ma zapobiegać (audyt 18.09.2026). Pilnuje tego test
  // czytający klucze z komponentów.
  qc.setQueryData(
    ["clients-lookup-add-project", "contract-eligible"],
    [
      { id: 1, name: "Bank Sigma" },
      { id: 2, name: "Bank Omega" },
      { id: 3, name: "UBEZPIECZENIA SIGMA - ODDZIAŁ W POLSCE" },
    ],
  );
  // Wybór klienta w pasku filtrów (wersja B) — ten sam klucz co komponent.
  qc.setQueryData(
    ["clients-lookup-contracts-picker"],
    [
      { id: 1, name: "Bank Sigma" },
      { id: 2, name: "Bank Omega" },
    ],
  );
  for (const cid of ["1", "2", "3"]) {
    qc.setQueryData(
      ["add-project-jobs", cid],
      [{ id: 11, title: "Tester Mobile" }],
    );
  }
  return qc;
}

/**
 * Bezpiecznik sieci na czas życia harnessu: okna otwierane z panelu
 * (zakończenie, przepięcie klienta) pytają o klucze nie do zasiania.
 */
function useNetworkBlocked() {
  const [interceptorId] = useState(() =>
    api.interceptors.request.use(() =>
      Promise.reject(
        Object.assign(
          new Error("Harness /preview/contracts-consolidation nie wysyła zapytań."),
          { isAxiosError: true, code: "ERR_PREVIEW_OFFLINE" },
        ),
      ),
    ),
  );
  useEffect(
    () => () => {
      api.interceptors.request.eject(interceptorId);
    },
    [interceptorId],
  );
}

export default function ContractsConsolidationPreview() {
  useNetworkBlocked();
  const [ready, setReady] = useState(false);
  const [qc] = useState(seededClient);
  // `?contract=` pokazuje otwarty panel — dialog nie może go zasłaniać.
  const [dialogOpen, setDialogOpen] = useState(
    () =>
      typeof window === "undefined" ||
      !new URLSearchParams(window.location.search).has("contract"),
  );

  useEffect(() => {
    // Komponenty czytają rolę z produkcyjnego store'a — zasilamy go adminem
    // z view_finance, żeby kolumny stawek były widoczne na zrzucie.
    useAuthStore.setState({
      user: {
        id: 1,
        email: "preview@example.com",
        name: "Preview Admin",
        role: "admin",
        roles: ["admin"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
        capabilities: ["view_finance", "contract.create"],
        analytics_capabilities: ["view_finance"],
      } as never,
      hydrated: true,
    });
    setReady(true);
  }, []);

  if (!ready) {
    return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  }

  return (
    <ToastProvider>
      <QueryClientProvider client={qc}>
        <div className="min-h-screen bg-background p-6 space-y-10">
          <section>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              1. Lista kontraktów — jeden wiersz na osobę (Paweł Makietowy: Bank
              Sigma + Bank Omega)
            </h2>
            <ContractsListV2
              modeTabs={
                <WorkspaceModeTabs
                  label="Tryb modułu Kontrakty"
                  modes={[
                    { value: "operations", label: "Obsługa kontraktorów" },
                    { value: "register", label: "Rejestr kontraktów" },
                    { value: "order-mail", label: "Skrzynka zamówień", count: 3 },
                  ]}
                  value="register"
                  onChange={() => {}}
                />
              }
              toolbarLead={
                <ContractsClientPicker compact value={null} onChange={() => {}} />
              }
            />
          </section>

          <section>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              2. Dialog „+ Dodaj kolejny projekt” (Klient wymagany — spróbuj
              zapisać bez klienta)
            </h2>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setDialogOpen(true)}
            >
              Otwórz dialog
            </Button>
            <AddProjectDialog
              open={dialogOpen}
              onOpenChange={setDialogOpen}
              candidateId={10}
              candidateName="Paweł Makietowy"
              canManageFinance
              baseContract={{
                id: 467,
                client_id: 1,
                contract_type: "b2b",
                rate_unit: "hourly",
                currency: "PLN",
                billing_hours_per_month: 160,
                work_mode: "remote",
              }}
            />
          </section>
        </div>
      </QueryClientProvider>
    </ToastProvider>
  );
}
