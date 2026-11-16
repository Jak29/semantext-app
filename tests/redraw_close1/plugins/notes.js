// An async module with one long keyed text box (a note the person reads and scrolls), drawn at once; then it waits on a
// read of its own (globalThis.__hold) and writes when it was saved.
export async function render(data, el, helpers) {
  const h = helpers.h;
  el.replaceChildren(h("textarea", { "data-k": "long-note", value: data.text || ("line\n".repeat(400)) }), h("p", { class: "saved" }, "..."));
  if (globalThis.__hold) await globalThis.__hold;
  el.childNodes[1].replaceChildren("Saved " + (data.n || 0));
}
