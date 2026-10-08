"use client"

import { Switch as SwitchPrimitive } from "@base-ui/react/switch"
import { cn } from "cn"
import { useFieldLabel } from "@/components/field-context"

function Switch({
  className,
  size = "default",
  ...props
}: SwitchPrimitive.Root.Props & {
  size?: "sm" | "default"
}) {
  const labelledBy = useFieldLabel(props)
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      aria-labelledby={labelledBy}
      data-size={size}
      className={cn(
        "peer group/switch relative inline-flex shrink-0 items-center rounded-xl border border-field transition-all group-has-[:focus-visible]/field-label:border-transparent group-has-[:focus-visible]/field-label:ring-0 after:absolute after:-inset-x-3 after:-inset-y-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan aria-invalid:border-destructive data-[size=default]:h-6 data-[size=default]:w-10 data-[size=sm]:h-[16px] data-[size=sm]:w-[28px] data-checked:border-amber data-checked:bg-amber data-unchecked:bg-lift data-disabled:cursor-not-allowed data-disabled:border-dashed data-disabled:opacity-60",
        className
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        data-slot="switch-thumb"
        className="pointer-events-none ml-1 block rounded-full ring-0 transition-transform group-data-[size=default]/switch:size-4 group-data-[size=sm]/switch:size-2.5 group-data-[size=default]/switch:data-checked:translate-x-[14px] group-data-[size=sm]/switch:data-checked:translate-x-[11px] group-data-[size=default]/switch:data-unchecked:translate-x-0 group-data-[size=sm]/switch:data-unchecked:translate-x-0 data-checked:bg-on-amber data-unchecked:bg-muted-foreground"
      />
    </SwitchPrimitive.Root>
  )
}

export { Switch }
