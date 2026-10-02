import { Button as ButtonPrimitive } from "@base-ui/react/button"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "cn"

const buttonVariants = cva(
  "group/button inline-flex shrink-0 items-center justify-center rounded-lg border border-transparent bg-clip-padding text-[13px] leading-4 font-semibold tracking-[0.005em] whitespace-nowrap transition-colors outline-none select-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan disabled:cursor-not-allowed disabled:border-dashed disabled:border-field disabled:bg-transparent disabled:text-muted-foreground aria-invalid:border-destructive [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-amber-hover active:bg-amber-pressed disabled:bg-lift",
        outline:
          "border-hairline-strong bg-raised text-foreground hover:bg-lift active:bg-pressed aria-expanded:bg-lift",
        secondary:
          "border-hairline-strong bg-raised text-foreground hover:bg-lift active:bg-pressed aria-expanded:bg-lift",
        ghost: "text-foreground hover:bg-raised aria-expanded:bg-raised",
        destructive:
          "border-coral/50 bg-transparent text-destructive hover:bg-coral/12 active:bg-coral/18",
        link: "text-cyan hover:text-cyan-hover",
      },
      size: {
        default:
          "h-10 gap-2 px-3.5 has-data-[icon=inline-end]:pr-3 has-data-[icon=inline-start]:pl-3",
        xs: "h-7 gap-1 px-2 text-xs [&_svg:not([class*='size-'])]:size-3",
        sm: "h-8 gap-1.5 px-3 text-xs [&_svg:not([class*='size-'])]:size-3.5",
        lg: "h-11 gap-2 px-[18px]",
        icon: "size-10",
        "icon-xs": "size-7 [&_svg:not([class*='size-'])]:size-3",
        "icon-sm": "size-8",
        "icon-lg": "size-11",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  ...props
}: ButtonPrimitive.Props & VariantProps<typeof buttonVariants>) {
  return (
    <ButtonPrimitive
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
