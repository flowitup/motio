import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { Choice } from "@/components/form";
import type { Api, VideoTemplate } from "@/lib/api";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

/** Every template (the starter set first, then the owner's). */
export function useTemplates(api: Api) {
  return useQuery({ queryKey: ["templates"], queryFn: () => api.templates(), staleTime: 30_000 });
}

/** A picture of a template's look: the real renderer's frame, 9:16. */
export function TemplatePreview({ api, tpl, className }: { api: Api; tpl: Pick<VideoTemplate, "preview" | "name">; className?: string }) {
  return (
    <img
      src={api.mediaUrl(tpl.preview)}
      alt={tpl.name}
      loading="lazy"
      className={cn("aspect-[9/16] rounded-md border bg-muted object-cover", className)}
    />
  );
}

/**
 * The template for the video about to be made: "" = the channel's default one (the classic look when it has none),
 * "none" = no template at all. `channelTemplate` is the chosen channel's default, shown in the preview.
 */
export function TemplateChoice({
  api,
  value,
  onChange,
  channelTemplate,
  className,
  compact,
  channelDefault,
}: {
  api: Api;
  value: string;
  onChange: (v: string) => void;
  channelTemplate?: string;
  className?: string;
  compact?: boolean; // only the select (toolbars)
  channelDefault?: boolean; // the channel form: no "channel default" / "none", an empty value is the classic look
}) {
  const { data } = useTemplates(api);
  const list = data ?? [];
  const shown = value === "none" ? undefined : list.find((x) => x.key === (value || channelTemplate || "b:classic"));
  const options: [string, string][] = channelDefault
    ? [["", t.templates.classic], ...list.filter((x) => x.key !== "b:classic").map((x): [string, string] => [x.key, x.name])]
    : [["", t.templates.picker.channelDefault], ["none", t.templates.picker.none], ...list.map((x): [string, string] => [x.key, x.name])];
  if (compact) return <Choice value={value} onChange={onChange} options={options} label={t.templates.picker.label} className={className ?? "h-10 w-44"} />;
  return (
    <div className={cn("flex items-start gap-4", className)}>
      {shown && <TemplatePreview api={api} tpl={shown} className="w-[72px] shrink-0" />}
      <div className="grid min-w-0 flex-1 content-start gap-2">
        <Choice value={value} onChange={onChange} options={options} label={t.templates.picker.label} className="h-11 w-full max-w-[336px]" />
        {shown && <p className="max-w-[420px] text-xs leading-[18px] text-muted-foreground">{shown.note}</p>}
        <Link to="/templates" className="w-fit text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline">
          {t.templates.picker.manage}
        </Link>
      </div>
    </div>
  );
}
