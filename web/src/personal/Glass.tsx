import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

/** The frosted surface every card and pill on the personal home shares. */
export function Glass({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "personal-glass rounded-[28px] border border-white/40 bg-white/55 shadow-[0_10px_40px_-12px_rgba(20,45,90,0.25)] backdrop-blur-2xl",
        className,
      )}
      {...props}
    />
  );
}
