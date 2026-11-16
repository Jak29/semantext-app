export function render(data, el, helpers) {
  const h = helpers.h;
  el.append(h("p", { class: "tix-row" }, "Ticket one: the printer on floor two is broken"),
    h("p", { class: "tix-row" }, "Ticket two: " + (data.items || []).length + " items listed"));
}
