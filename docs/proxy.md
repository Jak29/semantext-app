# The proxy (v0)

The proxy sits between an AI tool and the Anthropic Messages API on this machine (127.0.0.1 only). It hands the tool
your card with every request, holds any tool call a gate in your space matches, and keeps a record of what it decided
before anything reaches the tool.

## State in 1.7.0

It is a library module, `semantext.proxy` (`serve(space_dir, home, card, port)`), tested end to end with the
Anthropic SDK. It is **not yet usable on its own**:

- there is no `semantext proxy serve` command yet;
- there is no channel for you to answer its asks: an ask is bound to the proxy's own run, and neither the app nor the
  command line can answer it yet. A held call therefore stays held (it fails closed).

## What it decides

- A call to a tool the agent does not declare is held when your space's default is hold.
- A call any gate matches is held, unless you said yes to exactly that call, once.
- Your latest message (your own text, never a tool's output) is read by the reader: a call whose act your words hold,
  question, offer as an option, set a condition on, defer, keep for yourself, name without plainly saying go, or both
  allow and forbid is held too. A plain go for now ("Publish it", "Publish it tonight") adds no hold: your space's
  gates decide that call. A go in your words never releases a held
  call. The act of a call is named from its shell command or tool name (`semantext/actclass.py`); a call it cannot
  name gets no hold from your words, and your space's gates decide it as before.
- When one call of a turn is held, the whole turn is held; the text the tool sees is fixed wording, never your words
  or the call's input.

## Limits

- Each connection carries one request; replies say `Connection: close`.
- The key-shape check bounds the open middles it scans (a password in a URL up to 4 KiB, a JWT segment up to 8 KiB, a
  PEM label up to 128 characters), so a longer one in a request is not recognised as a key.

- The act of a call is read from patterns: a command built at run time, a script run by name or an interpreter
  one-liner may not be named. That can only lose a hold your words asked for; it never releases anything.
- The record catches an edit to part of it, not a rewrite of the whole file by someone with its rights.
