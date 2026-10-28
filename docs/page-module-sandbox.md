# Page modules in a sandbox: the design

Status: designed, not built. What is built is a server-side guard (below). Until the sandbox lands, **a page module
can act as you on the page**: it can answer requests, teach and change rules, and change settings.

## The problem

An outside place may ship one ES module, served at `/v2/plugin/<name>.js` (pagemodule.py). Today the page imports it
into its own document, so it runs with the page's origin. A `fetch` from it carries the page's `Origin` and can set
the page's `X-Semantext: 1` header, which is all `do_POST` and `/api/answer` check. The Python side of a plug-in is
held to a budget, caps, closures and roots; its JavaScript side is not (the Fable review of 70f2d3c, finding 6).

## The design

1. **One frame per enabled place.** The page draws the place in
   `<iframe sandbox="allow-scripts" src="/v2/plugin-frame.html">`, with no `allow-same-origin`, so the frame's
   origin is opaque. No `allow-top-navigation`, `allow-popups`, `allow-forms` or `allow-modals`.
2. **The frame document has its own policy**, sent with it, and carries `sandbox` itself, so it is sandboxed even
   when opened on its own:

       default-src 'none'; script-src http://<host>/v2/plugin-shim.js blob:; style-src http://<host>/v2/style.css;
       img-src blob:; connect-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self';
       sandbox allow-scripts

   `<host>` is the address the request was made to (only this machine's own, `_host_ok`). The script source names the
   one shim file by full URL rather than `'self'`, since browsers have differed on what `'self'` means in an opaque
   origin. `connect-src 'none'` leaves the module no `fetch`, XHR, WebSocket or beacon at all.
3. **The page hands it the data.** The shim posts `{type: "ready"}` to its parent. The page answers that message only
   when `event.source` is that frame's window, and only once for each load of the frame: it reads the module's text
   (`/v2/plugin/<name>.js`, a same-origin read by the page) and posts `{type: "render", module, data}`, where `data`
   is that place's answer without the frame (as today). The target origin is `"*"`, since an opaque origin cannot be
   named; the frame is the page's own element, and what it is sent is that place's own data and nothing else.
4. **The shim keeps the contract.** It makes a blob of the module's text, imports it (`script-src blob:`), and calls
   `render(data, el, {h, text})` with its own copy of the text-only helpers, so an author's module is unchanged. A
   throw, a missing `render` or a failed import is posted back as `{type: "problem", why}`, and the page shows the
   problem line it shows today. The frame posts its height so the page can size it.
5. **What the frame cannot reach.** It has no cookies or storage of the page's origin, cannot read the parent's DOM,
   and every request it could make to `/api/...` is cross-origin from `null`: a POST names `Origin: null` and is
   refused by `_origin_ok`, and the `X-Semantext` header forces a preflight this server never grants. With
   `connect-src 'none'` none is even sent.
6. **The page's own policy** gains `frame-src 'self'` and nothing else.

### What stays possible, stated

- A module can navigate its own frame to another site, and so send that place's data out. The data is the place's
  own answer, built by the plug-in's Python, which already holds the process's whole reach (SECURITY.md, Plug-ins).
- A module can draw anything inside its frame, including text that looks like the page. The frame is drawn under the
  place's title and "added by <package>", outside the frame.

### How it is to be checked

In a real browser, not only in the node stand-in (tests/v2_dom.js has no frames or messages): the module renders
through the shim; `fetch("/api/answer")` from the module is blocked; `top.location` and `parent.document` throw; a
module that throws leaves the problem line; the frame opened on its own is still sandboxed. The pane this round was
built in blocks every sandboxed frame (`ERR_BLOCKED_BY_CLIENT`), so none of this could be run there, which is why the
sandbox is not built yet.

## The guard built now

`server.Handler._from_plugin_module`: every change (`do_POST`) whose `Referer` path is under `/v2/plugin/`, or whose
`Sec-Fetch-Dest` is anything but a plain fetch's `empty`, is refused (403). **A known limit:** a module imported into
the page that calls `fetch()` sends the page's own `Referer` (`/v2`) and `empty`, so the guard does not tell it apart.
It refuses a change made from a document, frame or worker loaded at a module's path, or one a browser marks as no
fetch. The sandbox above is what closes the rest.
