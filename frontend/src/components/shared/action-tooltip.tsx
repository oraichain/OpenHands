import { Tooltip } from "@heroui/react"
import { useTranslation } from "react-i18next"
import ConfirmIcon from "#/assets/confirm"
import RejectIcon from "#/assets/reject"
import { I18nKey } from "#/i18n/declaration"

interface ActionTooltipProps {
  type: "confirm" | "reject"
  onClick: () => void
}

export function ActionTooltip({ type, onClick }: ActionTooltipProps) {
  const { t } = useTranslation()

  const content =
    type === "confirm"
      ? t(I18nKey.CHAT_INTERFACE$USER_CONFIRMED)
      : t(I18nKey.CHAT_INTERFACE$USER_REJECTED)

  return (
    <Tooltip content={content} closeDelay={100}>
      <button
        data-testid={`action-${type}-button`}
        type="button"
        aria-label={
          type === "confirm"
            ? t(I18nKey.ACTION$CONFIRM)
            : t(I18nKey.ACTION$REJECT)
        }
        className="rounded-full bg-neutral-900 p-1 hover:brightness-75 dark:bg-tertiary"
        onClick={onClick}
      >
        {type === "confirm" ? <ConfirmIcon /> : <RejectIcon />}
      </button>
    </Tooltip>
  )
}
