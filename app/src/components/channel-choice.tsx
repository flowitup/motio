import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Choice } from "@/components/form";
import type { Api } from "@/lib/api";
import { t } from "@/i18n";

/** Kênh cho video sắp làm: chọn sẵn kênh mặc định. `channel` gửi cho engine (undefined khi chưa có kênh nào). */
export function useChannelChoice(api: Api) {
  const { data } = useQuery({ queryKey: ["channels"], queryFn: () => api.channels(), staleTime: 30_000 });
  const [picked, setPicked] = useState<string | null>(null);
  const channels = data ?? [];
  const value = picked ?? String(channels.find((c) => c.default)?.id ?? 0);
  return { channels, value, setValue: setPicked, channel: channels.length ? Number(value) : undefined };
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
