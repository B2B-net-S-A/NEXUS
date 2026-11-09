import { api } from "@/lib/api";

// Ekran „Umowy klientów”: lista i pliki z własnym uprawnieniem, bez notatek i kwot.
export type ClientContractStatus =
  | "draft"
  | "pending_signature"
  | "active"
  | "expired"
  | "terminated"
  | "superseded";

export interface ClientContractAmendmentRow {
  id: number;
  name: string;
  effective_date: string;
  filename: string | null;
  has_file: boolean;
}

export interface ClientContractRow {
  id: number;
  client_id: number;
  client_name: string;
  name: string;
  status: ClientContractStatus;
  effective_date: string | null;
  expiry_date: string | null;
  filename: string | null;
  has_file: boolean;
  amendments: ClientContractAmendmentRow[];
}

const BASE = "/api/client-contract-documents";

export const clientContractDocumentsApi = {
  list: () => api.get<ClientContractRow[]>(BASE).then((response) => response.data),
  contractFilePath: (contractId: number) => `${BASE}/${contractId}/file`,
  amendmentFilePath: (contractId: number, amendmentId: number) =>
    `${BASE}/${contractId}/amendments/${amendmentId}/file`,
};
