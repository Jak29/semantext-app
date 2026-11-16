// A list a person works in: each row has its title, an unkeyed note field (empty) and an unkeyed quantity field ("1").
// The fields of every row read alike (tag, attributes, class, value), as a list's fields do.
export function render(data, el, helpers) {
  const h = helpers.h;
  el.replaceChildren(h("ul", { class: "rows" }, (data.rows || []).map((r) => h("li", { class: "row" },
    h("span", { class: "title" }, r),
    h("input", { class: "note", placeholder: "a note" }),
    h("input", { class: "qty", value: "1" })))));
}
