// A module whose render is async (D25): it draws its rows at once, then waits on a read of its own (globalThis.__hold
// stands for a fetch; a hold that never resolves stands for a fetch that never answers).
export async function render(data, el, helpers) {
  const h = helpers.h;
  el.replaceChildren(h("p", { class: "tix-row" }, "Ticket one: the printer on floor two is broken"),
    h("p", { class: "tix-row" }, "Ticket two: " + (data.n || 0) + " items listed"));
  const hold = globalThis.__hold;
  if (hold) await hold;
}
