import { cn } from "#/utils/utils";
import { OptionalTag } from "./optional-tag";

interface SettingsInputProps {
  testId?: string;
  name?: string;
  label: string;
  type: React.HTMLInputTypeAttribute;
  defaultValue?: string;
  placeholder?: string;
  showOptionalTag?: boolean;
  isDisabled?: boolean;
  startContent?: React.ReactNode;
  className?: string;
  onChange?: (value: string) => void;
}

export function SettingsInput({
  testId,
  name,
  label,
  type,
  defaultValue,
  placeholder,
  showOptionalTag,
  isDisabled,
  startContent,
  className,
  onChange,
}: SettingsInputProps) {
  return (
    <label className={cn("flex flex-col gap-2 w-fit", className)}>
      <div className="flex items-center gap-2">
        {startContent}
        <span className="text-[14px] font-medium text-[#595B57]">{label}</span>
        {showOptionalTag && <OptionalTag />}
      </div>
      <input
        data-testid={testId}
        onChange={(e) => onChange?.(e.target.value)}
        name={name}
        disabled={isDisabled}
        type={type}
        defaultValue={defaultValue}
        placeholder={placeholder}
        className={cn(
          "bg-white dark:bg-[#1E1E1F] border border-neutral-1000 dark:border-[#232521] h-11 w-full rounded-lg p-2 placeholder:italic",
          "disabled:bg-[#2D2F36] disabled:border-[#2D2F36] disabled:cursor-not-allowed",
        )}
      />
    </label>
  );
}
