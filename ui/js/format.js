// Small formatting helpers shared by every component.

/** 1234 -> "1.2k", 850000 -> "850k", 1200000 -> "1.2M". */
export function fmtUsage(n) {
  if (n == null || Number.isNaN(Number(n))) return "";
  n = Math.max(0, Number(n));
  if (n < 1000) return String(Math.round(n));
  if (n < 10_000) return trim((n / 1000).toFixed(1)) + "k";
  if (n < 1_000_000) return Math.round(n / 1000) + "k";
  if (n < 10_000_000) return trim((n / 1_000_000).toFixed(1)) + "M";
  return Math.round(n / 1_000_000) + "M";
}
const trim = (s) => s.replace(/\.0$/, "");

/** "1.2M of 2.4M", or "about 2.1M" when there is no budget yet. */
export function usageText(u) {
  if (!u) return "";
  if (u.budget) return `${fmtUsage(u.spent || 0)} of ${fmtUsage(u.budget)}`;
  if (u.estimate) return `About ${fmtUsage(u.estimate)}`;
  if (u.spent) return `${fmtUsage(u.spent)} used`;
  return "";
}

/** What an option costs, in plain words. */
export function optionUsage(n) {
  if (n == null) return "";
  if (n <= 0) return "No extra usage";
  return `About ${fmtUsage(n)} more`;
}

export const STATUS = {
  idle: { word: "Ready", tone: "idle" },
  working: { word: "Working", tone: "work" },
  needs_you: { word: "Needs you", tone: "you" },
  paused: { word: "Paused", tone: "idle" },
  done: { word: "Done", tone: "ok" },
  done_open: { word: "Done", tone: "ok-open" },
  stopped: { word: "Stopped", tone: "idle" },
  crashed: { word: "Something broke", tone: "bad" },
};

export function statusWord(status, ended) {
  if (status === "done_open") {
    const n = ended?.open_items?.length || 1;
    return `Done (${n} ${n === 1 ? "thing" : "things"} open)`;
  }
  return (STATUS[status] || STATUS.idle).word;
}

/** A shorter form for very narrow screens. */
export function statusShort(status, ended) {
  if (status === "done_open") return `Done · ${ended?.open_items?.length || 1} open`;
  if (status === "crashed") return "Broken";
  return statusWord(status, ended);
}

export const TASK_STATUS = {
  waiting: "Waiting",
  working: "Working",
  done: "Done",
  needs_fix: "Needs a fix",
  skipped: "Skipped",
};

export const DELIVERABLE_LABEL = { website: "Website", prd: "PRD", hld: "HLD", lld: "LLD" };

export function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** Ratio clamped to 0..1, safe with missing numbers. */
export function ratio(a, b) {
  if (!b || b <= 0) return 0;
  return Math.max(0, Math.min(1, (a || 0) / b));
}
