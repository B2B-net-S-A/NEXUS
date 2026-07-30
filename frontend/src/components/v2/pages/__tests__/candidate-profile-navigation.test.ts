import { afterEach, describe, expect, it, vi } from "vitest";

import {
  candidateQueryKeys,
  candidateViewerScopeKey,
} from "@/components/v2/pages/candidate-query-keys";
import {
  candidateRecruitmentFocusHref,
  focusCandidateRecruitmentCard,
  parseCandidateProfileView,
  parseCandidateRecruitmentFocus,
  resolveVisibleRecruitmentFocus,
  withCandidateProfileView,
} from "@/components/v2/pages/candidate-profile-navigation";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("candidate profile navigation", () => {
  it("reads the five canonical sections and their subviews", () => {
    expect(
      parseCandidateProfileView(
        new URLSearchParams("tab=activity&activity=calls"),
      ),
    ).toMatchObject({
      section: "activity",
      activity: "calls",
      isLegacy: false,
    });
    expect(
      parseCandidateProfileView(
        new URLSearchParams("tab=documents&documents=contracts"),
      ),
    ).toMatchObject({ section: "documents", documents: "contracts" });
  });

  it("maps old deep links without losing their intent", () => {
    expect(
      parseCandidateProfileView(new URLSearchParams("tab=chat&msg=77")),
    ).toMatchObject({
      section: "activity",
      activity: "chat",
      isLegacy: true,
    });
    expect(parseCandidateProfileView(new URLSearchParams("tab=umowa"))).toMatchObject(
      {
        section: "documents",
        documents: "contracts",
        isLegacy: true,
      },
    );
  });

  it("opens Activity/History for a pipeline entry without an explicit tab", () => {
    expect(
      parseCandidateProfileView(new URLSearchParams("from=job&jobId=9"), {
        fromJob: true,
      }),
    ).toMatchObject({
      section: "activity",
      activity: "timeline",
      hasExplicitTab: false,
    });
  });

  it("writes a canonical view while preserving nav, job and message context", () => {
    const next = withCandidateProfileView(
      new URLSearchParams(
        "nav=search&pos=4&from=job&jobId=9&msg=77&activity=notes",
      ),
      { section: "documents", activity: "timeline", documents: "files" },
    );

    expect(next.get("tab")).toBe("documents");
    expect(next.get("documents")).toBe("files");
    expect(next.has("activity")).toBe(false);
    expect(next.get("nav")).toBe("search");
    expect(next.get("from")).toBe("job");
    expect(next.get("msg")).toBe("77");
  });

  it("parses only unambiguous positive safe focus identifiers", () => {
    expect(
      parseCandidateRecruitmentFocus(new URLSearchParams("focusJobId=42")),
    ).toBe(42);

    for (const value of [
      "",
      "0",
      "-1",
      "1.5",
      "1e2",
      " 42",
      "9007199254740992",
    ]) {
      expect(
        parseCandidateRecruitmentFocus(
          new URLSearchParams({ focusJobId: value }),
        ),
      ).toBeNull();
    }
  });

  it("builds only canonical, validated candidate recruitment links", () => {
    expect(candidateRecruitmentFocusHref(7, 42)).toBe(
      "/candidates/7?tab=recruitments&focusJobId=42",
    );
    expect(candidateRecruitmentFocusHref(0, 42)).toBeNull();
    expect(candidateRecruitmentFocusHref(7, -1)).toBeNull();
    expect(
      candidateRecruitmentFocusHref(7, Number.MAX_SAFE_INTEGER + 1),
    ).toBeNull();
  });

  it("allows focus only for a job in the authorised visible history", () => {
    const history = [{ job_id: 42 }, { id: 77 }, { job_id: "99" }];

    expect(resolveVisibleRecruitmentFocus(42, history)).toBe(42);
    expect(resolveVisibleRecruitmentFocus(77, history)).toBe(77);
    expect(resolveVisibleRecruitmentFocus(99, history)).toBeNull();
    expect(resolveVisibleRecruitmentFocus(100, history)).toBeNull();
    expect(resolveVisibleRecruitmentFocus(null, history)).toBeNull();
  });

  it("focuses and scrolls only a rendered, visible recruitment card", () => {
    const card = document.createElement("div");
    card.id = "candidate-recruitment-42";
    card.setAttribute("role", "group");
    card.setAttribute("aria-labelledby", "candidate-recruitment-42-title");
    card.tabIndex = -1;
    const title = document.createElement("span");
    title.id = "candidate-recruitment-42-title";
    title.textContent = "Senior Java Developer";
    card.append(title);
    const focus = vi.spyOn(card, "focus");
    const scrollIntoView = vi.fn();
    card.scrollIntoView = scrollIntoView;
    document.body.append(card);
    const matchMedia = vi.fn().mockReturnValue({ matches: false });
    vi.stubGlobal("matchMedia", matchMedia);

    const visibleFocus = resolveVisibleRecruitmentFocus(42, [{ job_id: 42 }]);
    expect(focusCandidateRecruitmentCard(visibleFocus)).toBe(true);
    expect(card).toHaveAccessibleName("Senior Java Developer");
    expect(focus).toHaveBeenCalledWith({ preventScroll: true });
    expect(matchMedia).toHaveBeenCalledWith(
      "(prefers-reduced-motion: reduce)",
    );
    expect(scrollIntoView).toHaveBeenCalledWith({
      behavior: "smooth",
      block: "center",
    });

    focus.mockClear();
    scrollIntoView.mockClear();
    const forbiddenFocus = resolveVisibleRecruitmentFocus(99, [
      { job_id: 42 },
    ]);
    expect(focusCandidateRecruitmentCard(forbiddenFocus)).toBe(false);
    expect(focus).not.toHaveBeenCalled();
    expect(scrollIntoView).not.toHaveBeenCalled();

    card.remove();
  });

  it("avoids smooth scrolling when reduced motion is preferred", () => {
    const card = document.createElement("div");
    card.id = "candidate-recruitment-42";
    card.tabIndex = -1;
    const scrollIntoView = vi.fn();
    card.scrollIntoView = scrollIntoView;
    document.body.append(card);
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockReturnValue({ matches: true }),
    );

    expect(focusCandidateRecruitmentCard(42)).toBe(true);
    expect(scrollIntoView).toHaveBeenCalledWith({
      behavior: "auto",
      block: "center",
    });

    card.remove();
  });
});

describe("candidate query keys", () => {
  it("normalises route string ids to numeric cache identities", () => {
    expect(candidateQueryKeys.detail("42")).toEqual(["candidate", 42]);
    expect(candidateQueryKeys.timeline("42", 3)).toEqual([
      "candidate-timeline",
      42,
      { limit: 3 },
    ]);
    expect(candidateQueryKeys.calls("42")).toEqual(["candidate-calls", 42]);
    expect(candidateQueryKeys.risk("42")).toEqual(["candidate-risk", 42]);
    expect(candidateQueryKeys.history("42", "viewer:17")).toEqual([
      "candidate-history",
      42,
      { viewerScope: "viewer:17" },
    ]);
    expect(candidateQueryKeys.historyRoot("42")).toEqual([
      "candidate-history",
      42,
    ]);
    expect(candidateQueryKeys.notes("42")).toEqual(["candidate-notes", 42]);
    expect(candidateQueryKeys.aiProfile("42")).toEqual([
      "candidate-ai-profile",
      42,
    ]);
    expect(candidateQueryKeys.documents("42")).toEqual([
      "candidate-documents",
      42,
    ]);
    expect(candidateQueryKeys.contracts("42")).toEqual([
      "candidate-contracts",
      42,
    ]);
    expect(candidateQueryKeys.recommendations("42", 10)).toEqual([
      "suggested-jobs",
      42,
      { topK: 10 },
    ]);
    expect(candidateQueryKeys.recommendationsRoot("42")).toEqual([
      "suggested-jobs",
      42,
    ]);
  });

  it("partitions sensitive profile caches by viewer and normalized role scope", () => {
    const viewerScope = candidateViewerScopeKey({
      id: 17,
      role: "recruiter",
      roles: ["sourcer", "recruiter"],
    });

    expect(viewerScope).toBe("viewer:17:roles:recruiter,sourcer");
    expect(
      candidateViewerScopeKey({
        id: 17,
        role: "recruiter",
        roles: ["recruiter", "sourcer"],
      }),
    ).toBe(viewerScope);
    expect(candidateViewerScopeKey(null)).toBeNull();
    expect(candidateQueryKeys.activitySummary("42", viewerScope!)).toEqual([
      "candidate-activity-summary",
      42,
      { viewerScope },
    ]);
    expect(candidateQueryKeys.history("42", viewerScope!)).toEqual([
      "candidate-history",
      42,
      { viewerScope },
    ]);
    expect(
      candidateQueryKeys.recentRecruitments("42", 5, viewerScope!),
    ).toEqual([
      "candidate-recent-recruitments",
      42,
      { limit: 5, viewerScope },
    ]);
  });
});
