import type { ReactNode } from "react";

export function CompactEmpty({ children }: { children: ReactNode }) {
  return <span className="qto-compact-empty" data-contract="global compact empty text no Ant Empty block; global low-emphasis empty state text; dashboard compact empty text no Ant Empty block">{children}</span>;
}
