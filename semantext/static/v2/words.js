// Words and times, as the page writes them.

// ---------------------------------------------------------------- words and times
export const plural = (n, one, many) => n + " " + (n === 1 ? one : (many || one + "s"));
export const stamp = (iso) => { const t = Date.parse(iso); return Number.isNaN(t) ? 0 : t; };
export function when(iso) {
  const d = new Date(iso);
  if (!iso || Number.isNaN(d.getTime())) return iso || "";
  return d.toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}
export function day(date) {
  if (!date) return "";
  const d = new Date(String(date).slice(0, 10) + "T12:00:00");
  return Number.isNaN(d.getTime()) ? String(date) : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}
export const clock = () => new Date().toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
export function listWords(items) {
  const xs = items.filter(Boolean);
  return xs.length <= 1 ? (xs[0] || "") : xs.slice(0, -1).join(", ") + " and " + xs[xs.length - 1];
}
export const cap = (s) => s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
// A long path by its last two folders, which tell paths apart; the whole path goes in the tooltip.
export function tail(path) {
  const parts = String(path || "").split(/[\\/]+/).filter(Boolean);
  const sep = String(path || "").includes("\\") ? "\\" : "/";
  return parts.length > 3 ? "…" + sep + parts.slice(-2).join(sep) : String(path || "");
}
// Cards newest first, as the inbox orders them; a tie keeps the order the files give.
export const newestFirst = (list) => list.slice().sort((a, b) => stamp(b.at) - stamp(a.at));
