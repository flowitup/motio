import { useQuery } from "@tanstack/react-query";
import { TriangleAlert } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useApi, type Stats } from "@/lib/api";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

const usd = (n: number) => `$${n.toFixed(2)}`;
const num = (n: number) => n.toLocaleString();

function Metric({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <Card className="gap-1 p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-2xl font-semibold tracking-tight">{value}</div>
      {note && <div className="text-xs text-muted-foreground">{note}</div>}
    </Card>
  );
}

/** Banner when the month is close to (or over) the budget set in Settings. */
function BudgetBanner({ budget }: { budget: Stats["budget"] }) {
  if (budget.state !== "warn" && budget.state !== "over") return null;
  const over = budget.state === "over";
  return (
    <div
      className={cn(
        "flex items-start gap-3 rounded-lg border px-4 py-3 text-sm",
        over ? "border-destructive/40 bg-destructive/10" : "border-amber-500/40 bg-amber-500/10",
      )}
    >
      <TriangleAlert className={cn("mt-0.5 size-4 shrink-0", over ? "text-destructive" : "text-amber-600")} />
      <div className="space-y-1">
        <p className="font-medium">
          {over ? t.stats.budgetOver(budget.usd) : t.stats.budgetWarn(Math.round(budget.ratio * 100), budget.usd)}
        </p>
        {budget.auto_paused && <p className="text-muted-foreground">{t.stats.autoPaused}</p>}
      </div>
    </div>
  );
}

/** Voice cost per day for the last 30 days: plain CSS bars, the tooltip carries the numbers. */
function DayChart({ days }: { days: Stats["days"] }) {
  const max = Math.max(...days.map((d) => d.usd), 0.01);
  return (
    <Card className="gap-3 p-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-medium">{t.stats.days}</h2>
        <span className="text-xs text-muted-foreground">{t.stats.dayCost}</span>
      </div>
      <div className="flex h-32 items-end gap-1" role="img" aria-label={t.stats.dayCost}>
        {days.map((d) => (
          <div
            key={d.date}
            className="flex h-full min-w-0 flex-1 items-end"
            title={t.stats.dayTip(d.date, d.videos, d.usd)}
          >
            <div
              className={cn("w-full rounded-t-sm", d.usd > 0 ? "bg-primary" : "bg-muted")}
              style={{ height: d.usd > 0 ? `${Math.max((d.usd / max) * 100, 4)}%` : "2px" }}
            />
          </div>
        ))}
      </div>
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>{days[0]?.date}</span>
        <span>{days[days.length - 1]?.date}</span>
      </div>
    </Card>
  );
}

function ChannelTable({ rows }: { rows: Stats["channels"] }) {
  if (!rows.length) return <p className="py-6 text-center text-sm text-muted-foreground">{t.stats.empty}</p>;
  const head = [
    t.stats.colChannel,
    t.stats.colVideos,
    t.stats.colSent,
    t.stats.colFailed,
    t.stats.colChars,
    t.stats.colCost,
    t.stats.colPerVideo,
  ];
  return (
    <Card className="gap-0 overflow-x-auto p-0">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-xs text-muted-foreground">
            {head.map((h, i) => (
              <th key={h} className={cn("px-4 py-2 font-medium", i === 0 ? "text-left" : "text-right")}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.channel ?? "none"} className="border-b last:border-0">
              <td className="px-4 py-2">
                {r.channel === null ? <span className="text-muted-foreground">{t.stats.noChannel}</span> : r.name}
              </td>
              <td className="px-4 py-2 text-right tabular-nums">{r.videos}</td>
              <td className="px-4 py-2 text-right tabular-nums">{r.sent}</td>
              <td className={cn("px-4 py-2 text-right tabular-nums", r.failed > 0 && "text-destructive")}>
                {r.failed}
              </td>
              <td className="px-4 py-2 text-right tabular-nums">{num(r.chars)}</td>
              <td className="px-4 py-2 text-right tabular-nums">{usd(r.usd)}</td>
              <td className="px-4 py-2 text-right tabular-nums">
                {r.usd_per_video === null ? "–" : usd(r.usd_per_video)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

export default function StatsPage() {
  const api = useApi()!;
  const { data, isLoading, error } = useQuery({ queryKey: ["stats"], queryFn: () => api.stats() });
  const perVideo = data && data.month.videos > 0 ? t.stats.perVideo(data.month.usd / data.month.videos) : undefined;

  return (
    <div className="mx-auto max-w-4xl space-y-5 p-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">{t.stats.title}</h1>
      </header>
      <p className="text-sm text-muted-foreground">{t.stats.hint}</p>
      {error && <p className="text-sm text-destructive">{error.message}</p>}
      {isLoading && <Skeleton className="h-40 w-full rounded-xl" />}
      {data && (
        <>
          <BudgetBanner budget={data.budget} />
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Metric
              label={t.stats.monthCost}
              value={usd(data.month.usd)}
              note={data.budget.usd > 0 ? t.stats.ofBudget(data.budget.usd) : undefined}
            />
            <Metric label={t.stats.monthVideos} value={String(data.month.videos)} note={perVideo} />
            <Metric label={t.stats.monthChars} value={num(data.month.chars)} />
            <Metric label={t.stats.total} value={usd(data.total.usd)} note={`${num(data.total.chars)}`} />
          </div>
          <DayChart days={data.days} />
          <section className="space-y-2">
            <h2 className="text-sm font-medium">{t.stats.byChannel}</h2>
            <ChannelTable rows={data.channels} />
          </section>
          <div className="space-y-1 text-xs text-muted-foreground">
            <p>{t.stats.price(data.price_per_1k)}</p>
            <p>{t.stats.notTracked}</p>
          </div>
        </>
      )}
    </div>
  );
}
