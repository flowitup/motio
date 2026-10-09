import * as React from "react"
import { cn } from "cn"
import { useFieldLabel } from "@/components/field-context"

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  const labelledBy = useFieldLabel(props)
  return (
    <textarea
      data-slot="textarea"
      aria-labelledby={labelledBy}
      className={cn(
        "flex field-sizing-content min-h-16 w-full rounded-lg border border-input bg-background px-3 py-2 text-[13px] transition-colors placeholder:text-muted-foreground/80 focus-visible:border-cyan focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan disabled:cursor-not-allowed disabled:border-dashed disabled:text-muted-foreground aria-invalid:border-destructive",
        className
      )}
      {...props}
    />
  )
}

export { Textarea }
