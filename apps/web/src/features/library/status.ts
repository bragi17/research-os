export const STATUS_STYLES: Record<string, { bg: string; text: string }> = {
  analyzed: { bg: "var(--accent-green-soft)", text: "var(--accent-green)" },
  deep_analyzed: { bg: "var(--accent-green-soft)", text: "var(--accent-green)" },
  light_analyzed: { bg: "var(--accent-blue-soft)", text: "var(--accent-blue)" },
  indexed: { bg: "var(--accent-green-soft)", text: "var(--accent-green)" },
  partial: { bg: "var(--accent-amber-soft)", text: "var(--accent-amber)" },
  pending: { bg: "var(--accent-amber-soft)", text: "var(--accent-amber)" },
  processing: { bg: "var(--accent-blue-soft)", text: "var(--accent-blue)" },
  failed: { bg: "var(--accent-red-soft)", text: "var(--accent-red)" },
};
