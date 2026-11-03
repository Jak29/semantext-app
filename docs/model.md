# A model on this machine (the model point, 1.6)

A model reads and proposes; it never decides. You set one model you started yourself on this machine, and ask it
with `semantext model ask`, at your own terminal. Each answer waits in your inbox as a proposal labelled **MODEL**,
never a rule, an answer or a decision: nothing is done with it unless you act. Nothing asks a model by itself: not the
page, not the card hook, not an agent.

## The settings

```
semantext model set --address http://127.0.0.1:11434 --model qwen3:8b --digest <the model's ID>
semantext model show
semantext model clear
semantext model check --file <the weights file> [--manifest <its manifest>]
```

### The digest is the model's ID, as `ollama list` shows it

Ollama keeps two digests for a model, and they are not the same:

- **The model's ID** is the sha256 of its **manifest**, a small file under
  `~/.ollama/models/manifests/registry.ollama.ai/library/<name>/<tag>`. `ollama list` shows its first 12 hex digits in
  the ID column, and the runtime reports it whole on every call. **This is what `--digest` takes**: the 12 digits
  `ollama list` shows, or all 64.
- **The weights** are a separate file under `~/.ollama/models/blobs/sha256-<hex>`, named by its own sha256. The
  manifest names it in its layer of type `application/vnd.ollama.image.model`. Its sha256 is **not** the model's ID,
  and given as `--digest` every call is refused.

To take the ID from the files rather than from the running runtime: hash the manifest yourself (in PowerShell,
`Get-FileHash <manifest> -Algorithm SHA256`) and compare its first 12 digits with what `ollama list` shows.
`semantext model check --file <weights> [--manifest <manifest>]` then checks the files on disk, separately from any
call: the manifest's bytes must hash to the ID you named, and the weights file's bytes to the blob that manifest
names. With no `--manifest`, it looks for Ollama's own, by the model's name.

A digest the runtime reports must be whole, all 64 hex digits; only yours may be the 12-digit ID.

| Setting | Default | What it does |
|---|---|---|
| `--address` | (none) | The one address the model may use: `http://127.0.0.1:PORT` or `http://[::1]:PORT`, exactly so. Refused: a name, even `localhost` (a name is looked up, and the hosts file or a resolver can point it anywhere); `0.0.0.0`; any other loopback (`127.0.0.2`) or spelling of these (`2130706433`, `0x7f.0.0.1`, `0177.0.0.1`, `127.1`, `::ffff:127.0.0.1`, `[0:0:0:0:0:0:0:1]`); a name or password in the address; https; a path. |
| `--model` | (none) | The model's name, as the runtime names it. |
| `--digest` | (none) | The model's ID: its manifest's sha256, 12 to 64 hex digits (see above). **With none, every call is refused**: a digest the runtime reports is only its claim, compared with yours on every call. |
| `--budget` | 60 | Seconds one call may take (0.1 to 600). At the budget the connection is shut. |
| `--tokens` | 512 | The cap on one answer's tokens (1 to 8192). Sent to the runtime as its limit, and counted as the answer streams: past it, the connection is shut. |
| `--on-mismatch` | `refuse` | When the runtime reports another digest than yours: `refuse` (nothing is sent) or `flag` (the call goes on, and the proposal shows the difference as a problem). |
| `--asks-per-hour` | 20 | Your own cap on asks in an hour (1 to 600). |

They are kept in your home's `state.json`, under `model_provider`. `record topics` uses them too: when they name the
model it asks, its version is checked against your digest (refused or flagged as above), and each topic line says how
its version was known: `matches yours`, `differs from yours`, or `the runtime's claim` when you named none.

## What a call may do

- **Read:** the card and the words you typed, handed to it as text. Nothing else: while it runs, every file open,
  folder listing and write made by the call's own thread, or by any thread it starts, is watched and refused outside
  what it was given. No other thread is judged: the page's server, a plug-in, anything else running in the process
  goes on as before. (Some routes are not watched at all; see the limits below.) A copy or a second name of a file it
  was not given is a read (M-SCOPE), and so is a Windows file call such as `_winapi.CreateFile`.
- **Never sent:** a card or words of yours holding something shaped like a key, a token or a password (the same
  pattern every reader in Semantext withholds). The call is refused (M-SCOPE) and nothing reaches the runtime: take it
  out of the rule or the words first. The wider check for long key-like runs applies, in Semantext, only to a reader
  off this machine; a model here is always on this machine.
- **Reach:** the one address, directly. No redirect is followed and no proxy is used. A host that is not a literal
  address (a name, or a spelling the resolver reads as an address: `2130706433`, `0x7f.0.0.1`, `0177.0.0.1`,
  `127.000.000.001`, `localhost.`) is refused at `connect`, `connect_ex`, `sendto` and `bind` before any lookup, since Python
  resolves a name inside those calls, before it announces anything, and a lookup that fails announces nothing.
- **Start:** no process, no native code (ctypes), and no thread the watch cannot follow.
- **Answer:** text, at most 4000 bytes, whole. Refused, and never shown cut: an answer over the cap, an answer that
  stops before the runtime says it is done, a tool call (structured, or dressed as text), a line in the shape of
  someone's words (`Jak said:`, `From:`), an answer in the inbox's `#12 2` form or an `enable model` line, and a
  direction override. A line like that inside a code block is shown as text.
  - *Someone's words* are read as a person reads them: Cyrillic and Greek letters that look Latin (`Јak:` with a
    Cyrillic J, `Frоm:` with a Cyrillic o, `saιd` with a Greek iota) are folded to the Latin letter first, and bold or
    italic marks around the name (`**Jak**:`) count as nothing. The fold is a small fixed table, not all of Unicode's
    confusables: other scripts' look-alikes (Armenian, Coptic, Latin small capitals) still pass. It is a list of
    forms, too: shapes such as `Message from Jak: ship it`, `Decision from Jak: approved`, `Jak - ship it`,
    `[Jak] ship it`, `Jak says yes`, `Per Jak, ship it` and `Approved by Jak.` are not on it, and pass.
  - *A tool call dressed as text* is judged against **a list of known formats, not a parser**: `<tool_call>`
    (Hermes, Qwen), `function_call`, `<invoke>`, Mistral's `[TOOL_CALLS]`, DeepSeek's `<｜tool▁call…｜>` tags,
    Llama's `<function=…>` and `<|python_tag|>`, a fenced `tool_code` block (Gemma), an `Action:` line, and any JSON
    object shaped like a call, wherever in the answer it starts, trying **at most 64 places** where one may start
    (each `{` or `[`), so that a hostile answer's cost stays bounded: an answer with more than 64 stray braces before
    a call passes. A format not on the list passes. Nothing is ever run either way: the kernel keeps the answer as
    text and executes none of it, so the list is a second guard.
- **One at a time.** A second call while one runs is refused. After a call cut while the runtime may still be
  generating (at the budget, at the token cap, or past the wall), the next waits out one budget, since some runtimes
  finish a request whose connection closed. Each `semantext model ask` is a new process, so the time of that cut is
  kept in your `state.json` as `model_cut`: the address and the time, nothing of the call. A stream the runtime ended
  itself is not a cut.

Each refusal names its rule: M-HOST, M-SCOPE, M-SPAWN, M-STATE, M-LATE, M-TOOL, M-QUOTE, M-SIZE, M-LABEL, M-ID,
M-FLIGHT, M-TOKENS, M-HOOK and M-RATE.

**Time and length: M-SIZE, M-BUDGET and M-TOKENS, side by side.** The three are easy to confuse; each is judged
somewhere else.

| Rule | What it means | Judged |
|---|---|---|
| M-SIZE | The provider's call did not return within its budget and a short grace; or an answer over the byte cap, or not whole. | On the clock and on the answer, by Semantext. |
| M-BUDGET | The provider returned, or was abandoned, while the generation went on; also the refusal when the provider shuts its connection at the budget. | At the runtime, by its own counters. Semantext cannot see a real runtime's counters, so there it is the kit's question; with the kit's fake runtime it is measured. |
| M-TOKENS | The runtime went past your token cap, by the stream's own count. | On the stream, by Semantext. |

M-BUDGET's cases, as the kit tests them on its fake runtime: a provider that closes late (it stops at its budget but
shuts the connection a second later), and one that returns its answer with the connection left open while the
runtime generates on. The kernel files that second one's answer, since it cannot see the runtime; the kit's verdict,
from the runtime's own counters, is M-BUDGET for both. A third case, a duplicate handle kept open after the close,
cannot be made against the built-in provider: it shuts the socket, and a shutdown ends the connection for every
handle. A real runtime has not been measured.

**The ask count fails closed.** Your cap counts the asks of the last hour by the system clock; an ask stamped in the
future (the clock was set back) counts as now, and stays counted until the clock is an hour past it.

## A proposal, wherever it shows

A proposal waits in Waiting with the label **MODEL** drawn on its card, from the kernel's own field, with the model's
name, version and the digest you named, and any problem. Your answer to it (Noted, or Set aside) keeps that label in
the Record, so a model's words never read there as an ordinary decision of yours. No agent can file a request that
looks like one: a request sent as exactly MODEL, in capitals, or titled with MODEL as its whole first word (then a
space, a colon, or nothing: "MODEL proposal ...", "MODEL: ..."), in any spelling that reads so (another script's
letters, a fullwidth form, an invisible character), is refused. An agent named "model" or "Model" after its folder,
and titles such as "MODELS to deploy?" or "MODEL-T pricing", are other words, and are filed as usual. No agent,
whatever its name, sees a proposal or your answer as its own.

## What is not covered (stated, not fixed)

- **A loopback port is not an identity.** Once your runtime stops, any program on this machine can listen on its port
  and will be sent the card and your words. The digest check catches one that reports another digest, not one that
  repeats yours. What a model may read (the card and your prompt) bounds that harm.
- **The watch is inside Semantext's own process, and sees only what Python announces.** It stops accidents and
  drift in reviewed code, not a determined author. Not seen: native code making its own system calls, and
  standard-library routes that announce nothing. Which routes announce depends on the Python version. Measured on
  Python 3.14.3 (Orithises's kit check): `os.stat`, `os.lstat`, `os.access` and `os.environ` are not seen, and
  `sqlite3.connect` is seen and refused (M-SCOPE). An earlier review, its version not recorded here, found
  `sqlite3.connect` not seen (it opened and wrote a database file with no file-open event), and named `mmap`, which
  was not separately measured. Count every one of these as possibly unseen on the version you run. A thread started
  before the call, and handed work by it, is not watched either; nor is a raw `_socket.socket` (the C type under
  `socket.socket`), whose connect skips the name check above.
- **The first act refused is the one named.** A route that reads a file or the registry before it connects (urllib's
  proxy lookup, for one) is refused at that read, M-SCOPE, and never reaches its connection.
- **How a call's threads are followed.** Python 3.13 and later announce a new thread; 3.10 to 3.12 do not. So the
  watch follows a thread where every version starts one, `threading.Thread.start`, which it replaces once for the life
  of the process (a pass-through for any thread no call owns), and it refuses a raw `_thread.start_new_thread` from a
  call's thread. Code that kept its own reference to the raw function before Semantext's model point was loaded, and
  calls it on Python 3.10 to 3.12, is not seen.
- **`model_cut` is written without a lock.** Two `semantext model ask` processes that are cut at the same moment can
  each write it, and one write can be lost; the wait then runs from the other's time. Only one call runs at a time in
  any one process, and asking is yours, at your console, so this needs two of your own asks cut together.
- **A clock set back ignores a cut.** The wait is measured on the system clock; if the clock is set back past the
  time of the cut, that cut is ignored and the next call is not held.
- **Process-wide changes are not refused.** Inside a call, `os.putenv` and `sys.path.append` are accepted, and they
  outlive the call in a process that goes on running; `os.access` and `os.lstat` are not seen either.
- **A provider can switch its own watch off.** The watch lives in the same process as the provider, so code inside a
  call can clear it. It stops accidents in reviewed code, not a determined author; only a provider run in a process of
  its own would make it a boundary, and that comes before any provider not written here.
- **At the wall, a hostile listener may never see a close.** When a call does not return in time the kernel abandons
  it, but cannot make the provider's connection close from outside: against a listener that drips one byte at a time
  inside a line, the connection stays open while the process runs. `semantext model ask` ends its process, which closes
  it; a long-lived page control would have to solve this first.
- **What a person can edit.** `state.json`, including the model settings and `model_cut`, is a plain file anyone with
  access to your files can change.
- **A runtime may finish a request whose connection closed.** The kit measures this on a fake runtime that counts
  its own tokens; on a real runtime it has not been measured.
- **The page's own control for asking is not built yet**, nor any way for an agent to ask.
