import { describe, expect, it } from "vitest";

import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import {
  parseCandidateProfileView,
  withCandidateProfileView,
} from "@/components/v2/pages/candidate-profile-navigation";

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
    expect(candidateQueryKeys.history("42")).toEqual([
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
});
