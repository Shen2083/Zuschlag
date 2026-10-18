"use client";

import * as React from "react";
import * as SliderPrimitive from "@radix-ui/react-slider";

import { cn } from "@/lib/utils";

/** Radix slider: arrow keys step, PageUp/PageDown jump, Home/End go to the bounds. */
export function Slider({
  className,
  thumbLabel,
  valueText,
  ...props
}: React.ComponentProps<typeof SliderPrimitive.Root> & { thumbLabel: string; valueText?: string }) {
  return (
    <SliderPrimitive.Root
      className={cn("relative flex h-5 w-full touch-none items-center select-none", className)}
      {...props}
    >
      <SliderPrimitive.Track className="relative h-1.5 grow overflow-hidden rounded-full bg-secondary">
        <SliderPrimitive.Range className="absolute h-full bg-primary" />
      </SliderPrimitive.Track>
      <SliderPrimitive.Thumb
        aria-label={thumbLabel}
        aria-valuetext={valueText}
        className="block size-4 rounded-full border-2 border-primary bg-card shadow focus-visible:ring-4 focus-visible:ring-ring/40 focus-visible:outline-none"
      />
    </SliderPrimitive.Root>
  );
}
