import { Badge } from "@/components/ui/badge";
import type { ProjectStatus } from "@/lib/api";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

const STYLE: Record<ProjectStatus, string> = {
  queued: "bg-muted text-muted-foreground",
  running: "bg-blue-500/15 text-blue-700 dark:text-blue-300",
  review: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  done: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  failed: "bg-red-500/15 text-red-700 dark:text-red-300",
};

export function StatusChip({ status, className }: { status: ProjectStatus; className?: string }) {
  return (
    <Badge variant="secondary" className={cn("border-transparent", STYLE[status], className)}>
      {t.projects.status[status] ?? status}
    </Badge>
  );
}

export function ScoreBadge({ score }: { score: number }) {
  const tone =
    score >= 75
      ? "bg-red-500 text-white"
      : score >= 50
        ? "bg-amber-500 text-white"
        : "bg-muted text-muted-foreground";
  return (
    <span className={cn("inline-flex h-9 w-11 shrink-0 items-center justify-center rounded-md text-sm font-bold", tone)}>
      {score}
    </span>
  );
}
