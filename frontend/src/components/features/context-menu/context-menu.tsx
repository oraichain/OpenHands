import React from "react"
import { cn } from "#/utils/utils"

interface ContextMenuProps {
  ref?: React.RefObject<HTMLUListElement | null>
  testId?: string
  children: React.ReactNode
  className?: React.HTMLAttributes<HTMLUListElement>["className"]
}

export function ContextMenu({
  testId,
  children,
  className,
  ref,
}: ContextMenuProps) {
  return (
    <ul
      data-testid={testId}
      ref={ref}
      className={cn(
        "rounded-md border border-neutral-1000 bg-white dark:bg-tertiary",
        className,
      )}
    >
      {children}
    </ul>
  )
}
