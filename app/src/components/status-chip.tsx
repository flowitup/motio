import type { ProjectStatus } from "@/lib/api";
import { LedLabel } from "@/components/studio";
import { t } from "@/i18n";

/** A project's status as an LED + its word (see studio.tsx). */
export function StatusChip({ status, className }: { status: ProjectStatus; className?: string }) {
  return (
    <LedLabel status={status} className={className}>
      {t.projects.status[status] ?? status}
    </LedLabel>
  );
}

export { ScoreBadge } from "@/components/studio";
