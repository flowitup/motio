import { createContext, useContext } from "react";

/** The id of the label of the `Field` around a control: inputs, selects and switches point at it with aria-labelledby. */
export const FieldLabelContext = createContext<string | undefined>(undefined);

/** `aria-labelledby` for a control, unless it already has its own name. */
export function useFieldLabel(props: { "aria-label"?: string; "aria-labelledby"?: string }): string | undefined {
  const id = useContext(FieldLabelContext);
  return props["aria-labelledby"] ?? (props["aria-label"] ? undefined : id);
}
