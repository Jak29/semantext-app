// A list of tickets, newest first, each with an unkeyed reply box and an unkeyed "assign to" field (a plain module: it keys
// nothing). The boxes of every ticket read alike while they are empty, as a list's fields do.
export function render(data, el, helpers) {
  const h = helpers.h;
  el.replaceChildren(h("h2", null, "Tickets, newest first"),
    h("div", { class: "list" }, (data.tickets || []).map((t) => h("div", { class: "ticket" },
      h("p", { class: "subject" }, t),
      h("textarea", { class: "reply" }),
      h("input", { class: "assignee" })))));
}
