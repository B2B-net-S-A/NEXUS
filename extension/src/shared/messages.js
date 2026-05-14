// Message types shared between content scripts, the options page, and the
// background service worker. Keep this file dependency-free — it's loaded
// into every context.

export const MSG = Object.freeze({
  GET_AUTH_STATE: "GET_AUTH_STATE",
  LOGIN: "LOGIN",
  LOGOUT: "LOGOUT",
  SET_BACKEND_URL: "SET_BACKEND_URL",
  GET_BACKEND_URL: "GET_BACKEND_URL",
  SEARCH_JOBS: "SEARCH_JOBS",
  ADD_CANDIDATE: "ADD_CANDIDATE",
  SYNC_LINKEDIN: "SYNC_LINKEDIN",
  AUTH_CHANGED: "AUTH_CHANGED",
  OPEN_OPTIONS: "OPEN_OPTIONS",
});

// Default backend (overridable from the options page). Localhost is useful
// when testing against `docker compose up` running on the same machine.
export const DEFAULT_BACKEND_URL = "https://api.nexus.dynaminds.pl";
export const DEFAULT_FRONTEND_URL = "https://nexus.dynaminds.pl";
