/*
 * NEXUS Outlook Add-in — taskpane logic (Phase 7.4).
 *
 * Flow:
 *   1. Office.onReady → render login OR lookup section based on stored JWT.
 *   2. On every Office.context.mailbox.item change, read sender email and
 *      call GET /api/candidates/check-exists.
 *   3. Render the candidate card (found) or empty state with "Dodaj" CTA.
 *
 * Auth strategy: NEXUS email/password → JWT held only in sessionStorage.
 * A one-time read migrates an old localStorage value, then deletes it.
 * Office SSO (Office.context.auth.getAccessToken) is a follow-up — requires
 * matching WebApplicationInfo block in the manifest and an AAD app exposing
 * a scope, which is out of scope here.
 */

(function () {
  "use strict";

  // Same-origin in production (manifest hosted on nexus.dynaminds.pl). The
  // backend lives at api.nexus.dynaminds.pl, so use that. Compile-time
  // constant — if NEXUS gets a custom hostname, change here only.
  var API_BASE = "https://api.nexus.dynaminds.pl";
  var PROFILE_BASE = "https://nexus.dynaminds.pl";
  var TOKEN_KEY = "nexus.addin.jwt";

  // ── DOM handles (resolved after DOMContentLoaded — Office.onReady fires
  //    after the document is ready). ─────────────────────────────────────────
  var els = {};

  function $(id) { return document.getElementById(id); }

  function getToken() {
    try {
      var current = window.sessionStorage.getItem(TOKEN_KEY);
      if (current) return current;
      var legacy = window.localStorage.getItem(TOKEN_KEY);
      if (legacy) {
        window.sessionStorage.setItem(TOKEN_KEY, legacy);
        window.localStorage.removeItem(TOKEN_KEY);
      }
      return legacy;
    }
    catch (_) { return null; }
  }

  function setToken(token) {
    try {
      window.localStorage.removeItem(TOKEN_KEY);
      window.sessionStorage.setItem(TOKEN_KEY, token);
    }
    catch (_) { /* private mode or storage disabled — fall through */ }
  }

  function clearToken() {
    try {
      window.sessionStorage.removeItem(TOKEN_KEY);
      window.localStorage.removeItem(TOKEN_KEY);
    }
    catch (_) { /* ignore */ }
  }

  function show(el) { if (el) el.hidden = false; }
  function hide(el) { if (el) el.hidden = true; }

  function showError(target, message) {
    if (!target) return;
    target.textContent = message;
    show(target);
  }

  function clearError(target) {
    if (!target) return;
    target.textContent = "";
    hide(target);
  }

  // ── API ──────────────────────────────────────────────────────────────────

  async function login(email, password) {
    var resp = await fetch(API_BASE + "/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: email, password: password }),
    });
    if (!resp.ok) {
      var detail = "Logowanie nieudane (HTTP " + resp.status + ")";
      try {
        var body = await resp.json();
        if (body && body.detail) detail = body.detail;
      } catch (_) { /* ignore parse errors */ }
      throw new Error(detail);
    }
    var data = await resp.json();
    if (!data.access_token) throw new Error("Brak access_token w odpowiedzi.");
    return data.access_token;
  }

  async function checkExists(email) {
    var token = getToken();
    if (!token) throw new Error("Brak tokena — zaloguj się ponownie.");
    var url = API_BASE + "/api/candidates/check-exists?email=" + encodeURIComponent(email);
    var resp = await fetch(url, {
      headers: { "Authorization": "Bearer " + token },
    });
    if (resp.status === 401) {
      clearToken();
      throw new Error("Sesja wygasła — zaloguj się ponownie.");
    }
    if (!resp.ok) {
      throw new Error("Błąd lookup (HTTP " + resp.status + ").");
    }
    return await resp.json();
  }

  // ── Rendering ────────────────────────────────────────────────────────────

  function formatTimestamp(iso) {
    if (!iso) return "—";
    try {
      var date = new Date(iso);
      if (isNaN(date.getTime())) return "—";
      return date.toLocaleString("pl-PL", {
        year: "numeric", month: "short", day: "numeric",
        hour: "2-digit", minute: "2-digit",
      });
    } catch (_) {
      return "—";
    }
  }

  function renderFound(data, senderEmail) {
    hide(els.resultNotFound);
    hide(els.errorBox);
    els.candidateName.textContent = data.candidate_name || "—";
    els.currentStage.textContent = data.current_stage || "brak etapu";
    els.lastActivity.textContent = formatTimestamp(data.last_activity_at);
    els.openProfile.href = data.profile_url || PROFILE_BASE;
    show(els.resultFound);
  }

  function renderNotFound(senderEmail) {
    hide(els.resultFound);
    hide(els.errorBox);
    els.missingSender.textContent = senderEmail;
    // Pre-fill the "Add candidate" form with the sender email.
    var addUrl = PROFILE_BASE + "/candidates?prefill_email=" +
      encodeURIComponent(senderEmail);
    els.addCandidate.href = addUrl;
    show(els.resultNotFound);
  }

  function setStatus(text) {
    if (els.status) els.status.textContent = text;
  }

  function getSelectedSender() {
    try {
      var item = Office.context && Office.context.mailbox &&
        Office.context.mailbox.item;
      if (!item) return null;
      var from = item.from;
      // Drafts and meeting requests can omit `from`; fall back to `sender`.
      var who = from || item.sender || null;
      if (!who) return null;
      return (who.emailAddress || "").toLowerCase();
    } catch (_) {
      return null;
    }
  }

  async function runLookup() {
    var sender = getSelectedSender();
    if (!sender) {
      setStatus("Wybierz wiadomość, aby sprawdzić nadawcę.");
      hide(els.resultFound);
      hide(els.resultNotFound);
      return;
    }
    els.senderLine.textContent = "Nadawca: " + sender;
    setStatus("Sprawdzanie w bazie NEXUS…");
    hide(els.resultFound);
    hide(els.resultNotFound);
    hide(els.errorBox);
    try {
      var data = await checkExists(sender);
      setStatus("");
      if (data.found) renderFound(data, sender);
      else renderNotFound(sender);
    } catch (err) {
      setStatus("");
      showError(els.errorBox, err && err.message ? err.message : String(err));
      if (!getToken()) {
        // Token was cleared by checkExists on 401 — swap to login surface.
        showLoginSection();
      }
    }
  }

  // ── Sections ─────────────────────────────────────────────────────────────

  function showLoginSection() {
    hide(els.lookupSection);
    show(els.loginSection);
  }

  function showLookupSection() {
    hide(els.loginSection);
    show(els.lookupSection);
    runLookup();
  }

  // ── Event wiring ─────────────────────────────────────────────────────────

  function wireLoginForm() {
    els.loginForm.addEventListener("submit", async function (event) {
      event.preventDefault();
      clearError(els.loginError);
      els.loginButton.disabled = true;
      els.loginButton.textContent = "Logowanie…";
      try {
        var token = await login(els.email.value.trim(), els.password.value);
        setToken(token);
        els.password.value = "";
        showLookupSection();
      } catch (err) {
        showError(els.loginError, err && err.message ? err.message : String(err));
      } finally {
        els.loginButton.disabled = false;
        els.loginButton.textContent = "Zaloguj";
      }
    });
  }

  function wireLogout() {
    els.logoutButton.addEventListener("click", function () {
      clearToken();
      showLoginSection();
    });
  }

  function wireOfficeEvents() {
    // Re-run lookup whenever the user clicks a different message in the
    // Outlook reading pane.
    try {
      Office.context.mailbox.addHandlerAsync(
        Office.EventType.ItemChanged,
        runLookup
      );
    } catch (_) {
      // ItemChanged isn't supported on every Outlook surface (e.g. Outlook
      // Mobile). The initial render still works; we just won't auto-refresh.
    }
  }

  function cacheElements() {
    els.loginSection = $("login-section");
    els.lookupSection = $("lookup-section");
    els.loginForm = $("login-form");
    els.email = $("email");
    els.password = $("password");
    els.loginButton = $("login-button");
    els.loginError = $("login-error");
    els.logoutButton = $("logout-button");
    els.senderLine = $("sender-line");
    els.status = $("status");
    els.resultFound = $("result-found");
    els.candidateName = $("candidate-name");
    els.currentStage = $("current-stage");
    els.lastActivity = $("last-activity");
    els.openProfile = $("open-profile");
    els.resultNotFound = $("result-not-found");
    els.missingSender = $("missing-sender");
    els.addCandidate = $("add-candidate");
    els.errorBox = $("error-box");
  }

  // ── Bootstrap ────────────────────────────────────────────────────────────

  Office.onReady(function (info) {
    cacheElements();
    wireLoginForm();
    wireLogout();
    wireOfficeEvents();
    if (info && info.host !== Office.HostType.Outlook) {
      setStatus("Ten dodatek działa tylko w Outlook.");
      return;
    }
    if (getToken()) showLookupSection();
    else showLoginSection();
  });
})();
