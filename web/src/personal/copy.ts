import { useI18n } from "@/i18n";
import { en } from "@/i18n/en";
import type { PersonalTranslations } from "@/i18n/types";

/** Personal-home copy for the active locale, English until a locale translates it. */
export function usePersonalCopy(): PersonalTranslations {
  const { t } = useI18n();
  return t.personal ?? (en.personal as PersonalTranslations);
}
