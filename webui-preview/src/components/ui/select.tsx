import { useId, useRef, useState } from "react";
import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/utils";

export type SelectOption = {
  value: string;
  label: string;
  disabled?: boolean;
};

export type SelectControlProps = {
  value: string;
  onValueChange: (value: string) => void;
  options: readonly SelectOption[];
  className?: string;
  "aria-label"?: string;
  "aria-describedby"?: string;
  disabled?: boolean;
  required?: boolean;
  id?: string;
  name?: string;
};

/** A themed, keyboard-accessible selector that retains native form values. */
export function SelectControl({
  value,
  onValueChange,
  options,
  className,
  disabled,
  required,
  id,
  name,
  "aria-label": label,
  "aria-describedby": describedBy,
}: SelectControlProps) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const uniqueId = useId();
  let emptyItem = `vexbot:empty:${uniqueId}`;
  while (options.some((option) => option.value === emptyItem)) emptyItem += ":";
  const emptyOption = options.find((option) => option.value === "");
  const selectedOption = options.find((option) => option.value === value);

  return (
    <div
      className="min-w-0"
      onInvalidCapture={(event) => {
        // Radix's hidden native select retains required validation. Move its
        // validation focus to the visible control instead of an invisible input.
        event.preventDefault();
        trigger.current?.focus();
        setOpen(true);
      }}
    >
      <SelectPrimitive.Root
        value={value}
        onValueChange={(next) => onValueChange(next === emptyItem ? "" : next)}
        open={open && !disabled}
        onOpenChange={setOpen}
        disabled={disabled}
        required={required}
        name={name}
      >
        <SelectPrimitive.Trigger
          ref={trigger}
          type="button"
          id={id}
          aria-label={label}
          aria-describedby={describedBy}
          className={cn("vex-select-trigger", className)}
          data-slot="select-trigger"
          data-empty={required && value === "" ? "true" : undefined}
          title={selectedOption?.label}
        >
          <SelectPrimitive.Value
            className="vex-select-value"
            placeholder={emptyOption?.label ?? "请选择"}
          >
            {selectedOption?.label ?? (value || "请选择")}
          </SelectPrimitive.Value>
          <SelectPrimitive.Icon asChild>
            <ChevronDown className="vex-select-chevron" aria-hidden="true" />
          </SelectPrimitive.Icon>
        </SelectPrimitive.Trigger>
        <SelectPrimitive.Portal>
          <SelectPrimitive.Content
            className="vex-select-content"
            data-slot="select-content"
            position="popper"
            align="start"
            sideOffset={6}
            collisionPadding={12}
          >
            <SelectPrimitive.ScrollUpButton className="vex-select-scroll">
              <ChevronUp className="size-4" aria-hidden="true" />
            </SelectPrimitive.ScrollUpButton>
            <SelectPrimitive.Viewport className="vex-select-viewport">
              {options.map((option) => {
                const selected =
                  option.value === value && !(required && value === "");
                return (
                  <SelectPrimitive.Item
                    key={option.value}
                    value={option.value === "" ? emptyItem : option.value}
                    textValue={option.label}
                    disabled={option.disabled}
                    className="vex-select-option"
                    data-slot="select-item"
                    data-state={selected ? "checked" : "unchecked"}
                    aria-selected={selected}
                    title={option.label}
                  >
                    <SelectPrimitive.ItemText className="vex-select-option-text">
                      {option.label}
                    </SelectPrimitive.ItemText>
                    {selected && (
                      <Check className="vex-select-check" aria-hidden="true" />
                    )}
                  </SelectPrimitive.Item>
                );
              })}
            </SelectPrimitive.Viewport>
            <SelectPrimitive.ScrollDownButton className="vex-select-scroll">
              <ChevronDown className="size-4" aria-hidden="true" />
            </SelectPrimitive.ScrollDownButton>
          </SelectPrimitive.Content>
        </SelectPrimitive.Portal>
      </SelectPrimitive.Root>
    </div>
  );
}
