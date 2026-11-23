import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router";
import { Choice } from "@/components/form";
import type { Api } from "@/lib/api";
import { t } from "@/i18n";

/** Kênh (và mẫu video) cho video sắp làm: chọn sẵn kênh mặc định. `channel` / `template` gửi cho engine (undefined = mặc định). */
export function useChannelChoice(api: Api) {
  const { data } = useQuery({ queryKey: ["channels"], queryFn: () => api.channels(), staleTime: 30_000 });
  const [picked, setPicked] = useState<string | null>(null);
  const [params] = useSearchParams();
  const [tpl, setTemplate] = useState(() => params.get("template") ?? ""); // "" = the channel's default template, "none" = no template
  const channels = data ?? [];
  const value = picked ?? String(channels.find((c) => c.default)?.id ?? 0);
  const picks = channels.find((c) => String(c.id) === value);
  return {
    channels,
    value,
    setValue: setPicked,
    channel: channels.length ? Number(value) : undefined,
    /** The video template key to send (undefined = the channel's default). */
    template: tpl || undefined,
    templateValue: tpl,
    setTemplate,
    /** The default template of the chosen channel (for the preview). */
    channelTemplate: picks?.template || undefined,
  };
}

export type ChannelChoiceState = ReturnType<typeof useChannelChoice>;

/** Ô chọn kênh (kèm nhãn `label` phía trước nếu có); ẩn khi chưa có kênh nào. */
export function ChannelChoice({
  choice,
  label,
  className,
}: {
  choice: ChannelChoiceState;
  label?: string;
  className?: string;
}) {
  if (!choice.channels.length) return null;
  const select = (
    <Choice
      value={choice.value}
      onChange={choice.setValue}
      options={[["0", t.channels.none], ...choice.channels.map((c): [string, string] => [String(c.id), c.name])]}
      className={className}
    />
  );
  if (!label) return select;
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <span>{label}</span>
      {select}
    </div>
  );
}
