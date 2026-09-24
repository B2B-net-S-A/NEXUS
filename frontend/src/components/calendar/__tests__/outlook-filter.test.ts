import { describe, expect, it } from "vitest";

import { isOtherOutlookMeeting } from "@/components/calendar/calendar-config";

const base = { external_source: "microsoft365", event_type: "meeting", candidate_id: undefined, job_id: undefined };

describe("isOtherOutlookMeeting — co Tydzień chowa domyślnie", () => {
  it("zwykłe spotkanie z Outlooka albo iCal bez kandydata i rekrutacji", () => {
    expect(isOtherOutlookMeeting(base)).toBe(true);
    expect(isOtherOutlookMeeting({ ...base, external_source: "ical" })).toBe(true);
  });

  it("wszystko z pracy rekrutacyjnej zostaje widoczne", () => {
    expect(isOtherOutlookMeeting({ ...base, event_type: "prep_call" })).toBe(false);
    expect(isOtherOutlookMeeting({ ...base, event_type: "client_interview" })).toBe(false);
    expect(isOtherOutlookMeeting({ ...base, candidate_id: 5 })).toBe(false);
    expect(isOtherOutlookMeeting({ ...base, job_id: 7 })).toBe(false);
    // Założone w NEXUSIE — nigdy nie chowamy.
    expect(isOtherOutlookMeeting({ ...base, external_source: null })).toBe(false);
    expect(isOtherOutlookMeeting({ ...base, external_source: "manual" })).toBe(false);
  });
});
