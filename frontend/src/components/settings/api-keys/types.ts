import type {
  ScopeInfoDto,
  ServiceAccountConfigDto,
  ServiceAccountCreatePayload,
  ServiceAccountDto,
  ServiceAccountKeyCreatePayload,
  ServiceAccountKeyCreateResponse,
  ServiceAccountUpdatePayload,
  ServiceAccountWriteDto,
} from "@/lib/api";

/** Stan ładowania ekranu. Pusta lista kont istnieje tylko w `success` —
 *  awaria zapytania nie może wyglądać jak „brak kont”. */
export type ApiKeysLoad =
  | { status: "loading" }
  | { status: "error"; message: string; forbidden?: boolean; onRetry?: () => void }
  | {
      status: "success";
      accounts: ServiceAccountDto[];
      scopes: ScopeInfoDto[];
      config: ServiceAccountConfigDto;
    };

export type AccountWritesState =
  | { status: "loading" }
  | { status: "error"; message: string; onRetry?: () => void }
  | { status: "success"; writes: ServiceAccountWriteDto[] };

/** Zapisy na serwerze. Odrzucona obietnica = błąd pokazany przy akcji
 *  (tekst przez `apiErrorMessage`). */
export interface ApiKeysActions {
  createAccount: (payload: ServiceAccountCreatePayload) => Promise<unknown>;
  updateAccount: (id: number, payload: ServiceAccountUpdatePayload) => Promise<unknown>;
  deleteAccount: (id: number) => Promise<unknown>;
  issueKey: (
    id: number,
    payload: ServiceAccountKeyCreatePayload,
  ) => Promise<ServiceAccountKeyCreateResponse>;
  revokeKey: (id: number, keyId: string, reason: string | null) => Promise<unknown>;
}

/** Klucz pokazany raz, zaraz po wydaniu — żyje tylko w stanie ekranu. */
export interface RevealedApiKey {
  accountId: number;
  keyLabel: string;
  apiKey: string;
}
