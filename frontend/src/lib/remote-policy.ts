import type { RemotePolicy } from "@/types/client-profile";

/**
 * Opcje trybu pracy formularza rekrutacji — typowane z `RemotePolicy`
 * (`types/client-profile.ts`, lustro `backend/app/models/job.py::RemotePolicy`).
 * Pusta wartość = „nie ustawiono" (0278: kolumna `jobs.remote_policy` nie ma
 * domyślnej „hybrid" — brak wyboru jest uczciwym stanem, nie zgadywaniem).
 */
export const REMOTE_POLICY_OPTIONS: ReadonlyArray<{
  value: RemotePolicy | "";
  label: string;
}> = [
  { value: "", label: "— nie ustawiono —" },
  { value: "onsite", label: "On-site" },
  { value: "hybrid", label: "Hybrid" },
  { value: "remote", label: "Remote" },
];
