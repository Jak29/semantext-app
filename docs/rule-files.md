# Rule files

Every environment is one YAML file:

```text
~/.semantext/profiles/<environment>/SEMANTICS.yaml
```

`semantext where` prints the path of the active one. The file has three top-level keys: `environment`, `entries` and
`tests`. [examples/writing-desk/SEMANTICS.yaml](../examples/writing-desk/SEMANTICS.yaml) is a complete one you can
copy.

## `environment`

| Field | Meaning |
|---|---|
| `id` | The environment's name: lowercase, starting with a letter, then letters, digits or hyphens, at most 31 characters (`[a-z][a-z0-9-]{0,30}`). It is the folder's name, and it never changes once the file exists. |
| `version` | The file's version, such as `0.1.0`. |
| `status` | `candidate` for an environment you are still shaping. |
| `owner` | Who the rules belong to. |
| `title` | The human name. It heads the environment's section on the card. |
| `scope` | When this environment applies. The card shows it up to its first full stop. |
| `inherits` | `[base@0.1.0]`: the shared base rules, which come first on the card. |

`semantext env new TITLE...` writes this section for you:
- **The title** may use letters, numbers, spaces, apostrophes and hyphens, up to 40 characters.
- **The id** comes from the title: lowercased, with every run of other characters turned into one hyphen, and cut to 28
  characters. A title that starts with a digit gets `e-` in front.
- **A taken id** gets `-2`, `-3` and so on, so nothing is overwritten.
- **The scope** says what the environment was made for, and from how many suggested rules.

## `entries`

Each entry is one rule.

| Field | Meaning |
|---|---|
| `id` | `<environment>.<slug>`, such as `writing-desk.keep-the-voice`. It must be unique in the file. |
| `kind` | `rule`. |
| `statement` | The rule itself, as the AI will read it. |
| `applies_when` | When the rule matters. |
| `mode` | `stationary` or `adaptive`: a label kept with the rule, which `semantext pin RULE_ID` switches. Semantext never changes a rule by itself; refining rules from use is on the roadmap. |
| `enabled` | `true` puts the rule on the card. `false` keeps it in the file but off the card (`semantext toggle RULE_ID`). |
| `archived` | `true` once the rule is undone (`semantext undo RULE_ID`), with `archived_at` giving the time and `enabled` set to `false`. An undone rule stays in the file and never appears on the card. |
| `relay` | Optional. `true` puts the rule on the short card that a prompt gets when it is not your own message (see [card-format.md](card-format.md#the-relay-card)). |
| `always` | Optional. `true` puts the rule on every card, the relay card included. |
| `provenance` | Where the rule came from (below). |

### `provenance`

| `type` | Meaning | Other fields |
|---|---|---|
| `DEFAULT` | Shipped with Semantext. | `when` |
| `SETTING` | Written by you, on the page or in the file. | `when`, optionally `note` |
| `SUGGESTED` | Picked from a suggestion pack when the environment was made. | `pack`, `from` (the suggestion's id), `when` |
| `LEARNED` | Taught from a correction, with `semantext teach`, **Add rule** on the page, or an accepted proposal. | `words` (your exact words), `when`; for an agent's proposal you added in your own wording, `drafted_by` and `request`; for your sentence an agent wrote down from its session, `scribe` (the agent), `session`, and `prompt` (your message's `sha256`, `at` and the sentence's `offset`) |
| `PROPOSED` | Proposed by an agent from its own shell, and added by you as it was. Not your words, and the card says so. | `by` (the agent), `how` (how it was known), `request` (the inbox number), `proposed`, `added`, `via` (your terminal or the page) |

`semantext teach WORDS...` keeps your words twice: as the new rule's statement, and in `provenance.words`. The rule is
saved as `<environment>.learned-N` (with the `adaptive` label) and marked `(learned)` on the card. A correction must not be empty, and
must be under 400 characters. You can tidy the statement later on the page or in the file, and `provenance.words` keeps
what you actually said. Run from an agent's shell, `semantext teach` files the rule in your inbox as that agent's
proposal instead, and nothing reaches the file until you add it (see [inbox.md](inbox.md)).

A suggested rule, as `semantext env new Exam revision` writes it from the research pack:

```yaml
  - id: exam-revision.source-or-test
    kind: rule
    statement: Every claim carries a source or a test that could have failed. Otherwise call it a guess.
    applies_when: Always, in this environment.
    mode: stationary
    enabled: true
    provenance:
      type: SUGGESTED
      pack: research
      from: research.source-or-test
      when: "2026-10-13T12:00:00+00:00"
```

## `agents`

Optional: each agent's own rules in this environment, by the agent's name as `semantext agents` shows it.

```yaml
agents:
  reviewer:
    entries:
      - id: default.reviewer.learned-1
        kind: rule
        statement: Cite the file and the line for every point.
        applies_when: Learned from your correction; applies in this agent's own rules in this environment.
        mode: adaptive
        enabled: true
        provenance:
          type: LEARNED
          words: Cite the file and the line for every point.
          when: "2026-10-13T15:00:00+01:00"
```

- **Who gets them:** only that agent, in a section of its own after the shared rules. A name an agent merely states (a
  claim) gets none of them until you bind its folder to that name.
- **They follow a binding:** rules you taught an agent while it was seen by its tool and project (`claude-code@app`)
  go with it when you bind that project's folder, or a folder holding it, to a name. The deepest binding names the
  agent, so an outer binding never takes a project that a deeper one holds, and a binding of a subfolder takes none:
  outside that subfolder, the project's agent is still itself.
- **The `ai` layer:** rules for `ai` reach every agent Semantext cannot tell apart, meaning one with no binding, no
  tool it recognises and no stated name.
- **They never override:** the card says they add to the rules above, and that the rules above win in a conflict.
- **Writing them:** `semantext teach --agent NAME WORDS...` at your own terminal, or an agent's proposal you add.
  Their ids are `<environment>.<agent>.learned-N`, in one id space with the environment's own rules.
- **Changing them:** `toggle`, `pin` and `undo` take their ids, like any rule.

## `tests`

Your corrections, kept as tests of the rules taught from them. Each one is the message your AI got wrong, your own
words, and the rules a right reading needs. The list may be empty: `tests: []`.

```yaml
tests:
- case: default.case-1
  message: Could you tidy the README before the release?
  correction: 'When I say tidy, I mean format only: no rewording.'
  rules: [default.learned-3]
  source: person
  grounded: EXPLICIT
  at: '2026-10-14T11:02:31+01:00'
```

- **Writing them:** `semantext teach WORDS... --misread "the message"` at your own terminal, the correction box on
  the page's Today with the message it got wrong, or "Not read the way you meant?" under Try a message. A message that
  looks like it holds a key, a token or a password is refused, and so is one over 1,000 characters.
- **Checking them:** a test is **covered** while every rule it needs is in the file and switched on (an agent's own
  rule counts). Switching such a rule off, or removing it, is never blocked; the command line and the page say which
  of your corrections it uncovers, since that misreading can come back. `semantext cases` lists them, each covered or
  not.
- **On the card:** the environment's section ends with one line saying how many of your corrections are kept as tests
  for its rules. The messages themselves never go on the card.
- **Measuring with them:** the fields are the back-test's case fields ([backtest.md](backtest.md)), so
  `semantext cases --export cases.jsonl` writes a file for `semantext backtest --cases cases.jsonl`.
- **Your words:** a test holds a message you wrote, in the rule file, as a learned rule holds your correction. Keep
  that in mind before sharing an environment's file.

## The base environment

`base` holds the nine rules every environment shares, such as "a question asks for an answer" and "anything that
sends, publishes, spends, deletes, downloads or installs waits for your word". All nine are in
[card-format.md](card-format.md). `base` is never listed as an environment, and it cannot be made the active one.

## What the editor refuses

The page's editor saves a file only if it is still a valid environment. It refuses:
- YAML that does not parse;
- a file without an `environment` section;
- an `environment.id` that differs from the one already saved;
- `entries` that are not a list;
- an entry without an `id` or a `statement`;
- two entries with the same `id`;
- `tests` that are not a list, or a test without a `message`, or with `rules` that are not a list of ids.

If you edit the file by hand and break it, every command refuses with one line naming the broken file, and so does
the page. The hook prints one line saying the card is unavailable, and your prompt still goes through.

## History

Before every change Semantext makes, the previous file is copied to
`~/.semantext/history/<environment>-<timestamp>.yaml`.

- **Undoing one rule** archives it in place. It stays in the file, off the card.
- **Undoing the last change** (`semantext undo --last`) restores the newest saved version. The version being replaced
  is kept as `…-redo.yaml`, and the version restored is marked `…-used.yaml`, so the next undo goes one step further
  back.
- **Undoing with nothing saved** is refused.

Nothing is ever deleted.
