// Tekst błędu dla człowieka — jedno miejsce dla całego panelu.

import { ApiError } from "../api.js";

export function apiErrorText(err) {
  if (err instanceof ApiError || err?.name === "ApiError") return err.message;
  console.error("NEXUS: nieoczekiwany błąd panelu", err);
  return "Coś poszło nie tak. Spróbuj ponownie.";
}
