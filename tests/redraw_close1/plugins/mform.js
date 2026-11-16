// A form a plug-in might ship. Its render is async (D25). data.mode says when it draws its fields:
//   "first" (the common shape): the form is drawn at once, then the module waits on a read of its own (globalThis.__hold
//           stands for its fetch), then writes a status line under the form;
//   "last"  (the builder's test shape): it waits first and draws the form after.
export async function render(data, el, helpers) {
  const h = helpers.h;
  const form = () => [h("p", { class: "form-row" }, "Search the tickets"),
    h("input", { "data-k": "tix-q", value: data.q || "hello world" }),
    h("textarea", { "data-k": "tix-note", value: data.note || "first line of the note\nsecond line" }),
    h("input", { class: "unkeyed", value: data.u || "an unkeyed field" })];
  if (data.mode === "last") {
    if (globalThis.__hold) await globalThis.__hold;
    el.replaceChildren(...form(), h("p", { class: "status" }, "Results: " + (data.n || 0)));
    return;
  }
  el.replaceChildren(...form(), h("p", { class: "status" }, "Looking..."));
  if (globalThis.__hold) await globalThis.__hold;
  el.childNodes[el.childNodes.length - 1].replaceChildren("Results: " + (data.n || 0));
}
