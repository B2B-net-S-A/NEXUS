import type { CareerApplyFormProps } from "../CareerApplyForm";
import type { CareerJobResponse } from "@/lib/career/api";
import type { CareerBase } from "@/lib/career/host";

/** Wspólne propsy trzech układów ogłoszenia (szablony A/B/C, 28.10.2026). */
export interface CareerJobLayoutProps {
  /** Otwarta rekrutacja — zamkniętą obsługuje `ClosedNotice` w `CareerJobView`. */
  data: CareerJobResponse;
  base: CareerBase;
  /** Host żądania do stopki („kariera.b2bnetwork.pl”). */
  host: string;
  /** Harness `/preview/kariera`: stan formularza bez wysyłki. */
  formPreview?: CareerApplyFormProps["preview"];
}
