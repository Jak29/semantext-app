// The places a plug-in adds (semantext/pagemodule.py). Each is listed in the bar after the built-in places, with the
// package it came from. Its page module is imported from /v2/plugin/<name>.js the first time you go there, and its
// render(data, el, helpers) draws the place's data into a frame of its own. The helpers are dom.js's text-only ones,
// so a module never needs markup. A module that fails to load, offers no render, or throws, leaves a problem line in
// its frame, and the rest of the page goes on.
import { $, h } from "./dom.js";

export const HELPERS = Object.freeze({ h, text: (s) => document.createTextNode(String(s)) });
export const importer = { load: (url) => import(url) };
const modules = new Map();   // place name -> the promise of its module, imported once
let last = Promise.resolve();

export const outsidePlaces = (frame) => (frame && Array.isArray(frame.outside) ? frame.outside : []);
export const outsidePlace = (frame, name) => outsidePlaces(frame).find((p) => p.name === name) || null;
export const moduleUrl = (name) => "/v2/plugin/" + encodeURIComponent(name) + ".js";
export const settled = () => last;   // the latest drawing, done (the tests wait on it)

export function renderOutsideTabs(frame, current) {
  $("tabs-outside").replaceChildren(...outsidePlaces(frame).map((p) => h("a", {
    "data-place": p.name, href: "#" + encodeURIComponent(p.name), "aria-current": p.name === current ? "page" : null,
    title: "Added by " + p.origin + (p.version ? " " + p.version : "") + ", a plug-in you turned on",
  }, p.title || p.name, h("span", { class: "origin" }, p.origin))));
}

function problemLine(el, why) {
  el.replaceChildren(h("p", { class: "plugin-problem", role: "status" }, "This place's page module could not draw it: " + why));
}

export function drawOutside(place, data, el) {
  const frame = h("div", { class: "plugin-frame", "data-plugin": place.name });
  el.replaceChildren(h("p", { class: "meta" }, (place.title || place.name) + " · added by " + place.origin + (place.version ? " " + place.version : "")), frame);
  const body = Object.assign({}, data);
  delete body.frame;
  if (body.failed) { problemLine(frame, "the place stopped (" + body.failed + ")"); return (last = Promise.resolve()); }
  if (!place.module) {
    frame.replaceChildren(h("p", { class: "empty" }, "This place ships no page module, so its data is shown as it came."),
      h("pre", { class: "mono" }, JSON.stringify(body, null, 2)));
    return (last = Promise.resolve());
  }
  if (!modules.has(place.name)) modules.set(place.name, Promise.resolve().then(() => importer.load(moduleUrl(place.name))));
  last = modules.get(place.name).then((mod) => {
    if (!mod || typeof mod.render !== "function") throw new Error("it offers no render(data, el)");
    mod.render(body, frame, HELPERS);
  }).catch((e) => problemLine(frame, String((e && e.message) || e)));
  return last;
}
