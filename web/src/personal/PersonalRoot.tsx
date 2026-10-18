import { lazy, Suspense, type ReactNode } from "react";
import { useLocation } from "react-router";

import { ProfileProvider } from "@/contexts/ProfileProvider";
import { isPersonalPath } from "./lib/route";

const PersonalApp = lazy(() => import("./PersonalApp"));

/** The personal home is its own full-screen surface; every other path keeps the dashboard shell. */
export function PersonalRoot({ dashboard }: { dashboard: ReactNode }) {
  const { pathname } = useLocation();
  if (!isPersonalPath(pathname)) return dashboard;
  return (
    <ProfileProvider>
      <Suspense fallback={<div className="fixed inset-0 bg-[#79a5d6]" />}>
        <PersonalApp />
      </Suspense>
    </ProfileProvider>
  );
}
