import { useId, useRef, type ReactNode } from "react";
import { FieldLabelContext } from "@/components/field-context";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

/** A label above a control. The control (Input, Textarea, Select, Switch) takes its name from the label, and a click on the label focuses it. */
export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  const labelId = useId();
  const box = useRef<HTMLDivElement>(null);
  const focusControl = () =>
    box.current
      ?.querySelector<HTMLElement>("input:not([type=hidden]):not([type=file]):not(:disabled), textarea:not(:disabled), [role=combobox], [role=switch]")
      ?.focus();
  return (
    <FieldLabelContext.Provider value={labelId}>
      <div ref={box} className="grid gap-1.5">
        <Label id={labelId} onClick={focusControl}>
          {label}
        </Label>
        {children}
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </div>
    </FieldLabelContext.Provider>
  );
}

export function Choice({
  value,
  onChange,
  options,
  className,
  label,
}: {
  value: string;
  onChange: (v: string) => void;
  options: [string, string][];
  className?: string;
  label?: string; // accessible name when the Choice is not inside a Field
}) {
  return (
    <Select value={value} onValueChange={(v) => v != null && onChange(v)}>
      <SelectTrigger className={className ?? "w-full"} aria-label={label}>
        <SelectValue>{(v: string) => options.find(([k]) => k === v)?.[1] ?? v}</SelectValue>
      </SelectTrigger>
      <SelectContent>
        {options.map(([k, label]) => (
          <SelectItem key={k} value={k}>
            {label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
