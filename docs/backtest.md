# The back-test

`semantext backtest` scores your card against the misreadings you have actually had: the times you corrected your AI.
It runs on this machine, reads your transcripts, calls no model, and writes nothing.

```bash
semantext mine                      # first, if you like: your own past messages, kept as heard
semantext backtest                  # this project's Claude Code transcripts
semantext backtest --split 2026-10-01
semantext backtest --show           # also list the corrected messages the card is silent on
```

## What it measures

Each of your own messages is one unit. Your words are told apart from other agents' messages and tool notices the
same way the hook tells them apart (see [how-it-works.md](how-it-works.md)).

- **Misread:** a message you then corrected. Your next message, after the AI's reply, opened as a correction: "no, I
  meant ...", "that's not what I asked", "why did you ...".
- **Correction:** a message that was itself a correction, and was not corrected in turn. These are counted apart,
  because their own wording ("no, ...") always trips a reading.
- **Clean:** every other message of yours.

The card **touches** a message when its reading flags at least one rule for it: a base rule's cue (a question, a
maybe, a time limit, an act that needs your word), or one of your environment's rules sharing a meaningful word with
it. The plain fallback ("an instruction") never counts.

| measure | what it is |
|---|---|
| coverage | the share of misread messages the card touches |
| false-touch | the share of clean messages it touches |
| skill | coverage minus false-touch |

A card that touches everything has coverage and false-touch alike, and no skill. Each share comes with a 95%
interval (Wilson), and the skill with Newcombe's interval for a difference.

### Beside two null cards

The same messages are scored with two other cards:

- **the base rules alone**, with none of your environment's own;
- **as many rules as your card has, drawn from the suggestion packs** with a fixed seed. This card is the same size,
  but its words are other people's.

If your card scores like the drawn one, the back-test is measuring shared words, not fit.

### In-sample and out-of-sample

A rule taught from a correction will touch that same correction. So a score without `--split` is marked **in-sample**.
With `--split DATE`, rules learned on or after DATE are left off the card, and only messages from DATE on are scored:
the rules then meet messages they were not made from.

### What it does not measure

- **Touched is not prevented.** It says a rule bears on the message, not that an AI reading the card would have read
  it right. That needs a model reading the card, which the back-test does not call.
- **Only the misreadings you corrected count.** Silent misreadings, and wrong readings that happened to work, are
  invisible to it. The misread set is a floor, not a rate.
- **The correction openings are a list,** and a list misses many. A missed correction costs one row of the back-test,
  never a rule. `--finder` measures how many it misses. On one person's real transcripts, measured against corrections
  that person's own later words confirmed, the list was widened using half of them, and then found 4 of the other 16:
  about a quarter (an interval of 10% to 49%), and no demonstrable change from before the widening. Most corrections
  do not open in a form a list can recognise. It flagged 3.4% of all that person's messages, and at least a third of
  those flags are corrections the person later confirmed (a floor: the rest are unlabelled, not known to be wrong).
  Read the misread set as a sample of the plainly worded corrections, not of all of them.
- **"Clean" means no correction was detected.** Since the finder misses most corrections, some clean messages were in
  fact corrected. That pulls coverage and false-touch together, so a small skill slightly understates the card's.

## A weighed touch: `--weighed`

The plain touch counts any cue: a rule's reading, a decision verb, a word shared with a rule. Some cues fire as often
on ordinary messages as on misread ones, and carry nothing. `--weighed` weighs each cue by its evidence on your own
earlier messages, and sets the threshold so that at most a chosen share of your ordinary messages is touched:

```bash
semantext backtest --weighed                 # at most 10% of ordinary messages touched
semantext backtest --weighed --alpha 0.05
```

- **Cut by time.** The weights are fit on your earlier messages, the threshold is set on the next ordinary ones, and the
  score is taken on the later messages, which neither saw. Rules learned during the scored part are left off.
- **A ceiling that is checked, not assumed.** The threshold is a conformal one: if your ordinary messages are alike over
  time, a new one is touched with chance at most `--alpha`. The scored part checks whether that held.
- **Beside the plain touch,** on the same messages, with the precision gain (the share of touches that were misread,
  weighed minus plain) and its interval. The verdict is GO when the ceiling holds and both skill and the precision gain
  have intervals above zero, KILL when the ceiling fails or either is zero or below, and UNDERPOWERED between.
- **Counts only.** The report holds no message text, and nothing is written.

On one person's real history with the starter card, it touched 9.5% of ordinary messages (ceiling 10%) against 49%
for the plain touch, with a precision gain of +0.08 (0.02 to 0.15), on 15 held-out corrections: GO for that card on
that history, not a default for everyone.

## A model reading (optional): `--reader`

The cue-word reading says whether a rule could bear on a message. A model holding the card can say how it would read
it. With `--reader`, the back-test asks one, and scores its answers in the same harness:

```bash
semantext backtest --reader ollama:MODEL                       # a model on this machine, through Ollama
semantext backtest --cases cases.jsonl --reader ollama:MODEL --judge ollama:OTHER --judge ollama:THIRD --ablate
semantext backtest --reader endpoint:https://HOST/v1/chat/completions#MODEL --key-env MY_KEY_VARIABLE
```

- **Off unless you name a reader.** Without `--reader` nothing connects anywhere. A model on this machine keeps
  everything here; an endpoint outside it is announced before its first call, with what it will receive. An
  endpoint's key is read from the environment variable you name, at each call, and never stored. Each endpoint can
  name its own (`endpoint:URL#MODEL@VARIABLE`): one `--key-env` for endpoints on two hosts is refused, so a provider
  never receives another's key, and a key never goes over plain http to another machine.
- **No key leaves in your words.** A message, the reply before it, the card, and everything a judge is given are
  checked for key-like strings first; a hit is not sent, and the report counts it. Before anything leaves the
  machine, any long run of mixed letters and digits counts as one too.
- **What a reader sees:** the card (or no card, for the blind reading), the reply before the message, and the message,
  marked as data. Never your later correction, a case's expected or forbidden reading, your inbox or another
  environment's card. A message, or the reply before it, that looks like it holds a key, a token or a password is not
  sent; the report counts it.
- **What is taken from its answer:** one JSON object, the ids of the card's rules that bear on the message and one line
  of reading. Anything else is no reading, never a touch. The message may carry instructions aimed at the reader: its
  answer is data, and nothing acts on it.
- **Its reading is a measurement, never a rule.** It is labelled with the model and its version, kept in the report
  only, and never becomes a rule, a rule's provenance or a case's expected reading.
- **One fixed decoding, recorded.** A model on this machine reads with temperature 0, a context of 8,192 tokens and its
  thinking off. A thinking model can spend its whole context thinking and never answer: on one 36-billion-parameter
  local model, every reply came back empty with thinking on, and parsed with it off. A reply that reaches the context
  limit stops the run, because the card may have been cut. The report records the decoding, and the model's digest on
  this machine as its version, so a later pass can be checked against the same model, build and decoding.
- **The controls.** Touched and skill are scored against a same-size card drawn from the suggestion packs, read by the
  same model. A card larger than the packs gets a smaller null, and the report gives both sizes: a smaller card
  touches less, so a gap between them is partly size. For curated cases, each message is read twice, with the card and without it, in two independent calls in
  a random order. Two judges, each of another model lineage than the reader (qwen2.5 and qwen3.6 are one lineage;
  give `family=` where a name does not say it), decide whether each reading is the
  expected or the forbidden one; only their agreement counts, and the rest is DISPUTED. The paired result is tested
  with McNemar's exact test: the card helps only if the interval of the paired difference excludes zero. Messages
  from your transcripts are read the same way, blind and with the card; for the ones you corrected, the judges use a
  stated proxy (your correction as the expected reading, the reply you corrected as the forbidden one), reported apart
  from the curated cases. `--ablate` takes each needed rule out of the card in turn: the hits should fall on the cases
  that need it, and only there.
- **Power, stated.** The report gives the smallest net gain the test would find four times in five at its number of
  pairs, so a null on a small set reads as underpowered, not as "no effect".
- **A long history, read in part: `--clean-sample N`.** Each transcript message costs three calls (blind, with the
  card, with the null), so a long history takes hours on a local model. With `--clean-sample N`, every misread message
  is read, and N of the clean ones, drawn before any read with a fixed seed from the clean messages in their order.
  The report names the draw; a sample larger than the clean messages there are is refused.
- **One model at a time.** Every number belongs to the model that produced it. A result on a small local model says
  nothing about a larger one.

## Curated cases: `--cases FILE`

A JSON-lines file, one case per line. Only `message` is required.

| field | meaning |
|---|---|
| `message` | the words that were misread, verbatim |
| `context_before` | what came before them, if it matters |
| `reply_tail` | the end of the reply that misread them |
| `correction` | the person's own correction, verbatim |
| `source` | `person` (from the person's own words) or `curator` (written up by someone else) |
| `at` | when it was said |
| `supersedes` | an earlier case this one replaces; both stay on record |
| `grounded` | `EXPLICIT` when the person's own later words settle the right reading, `INFERRED` when a curator worked it out |
| `rules` | the rule ids a right reading needs |
| `categories` | free labels, for your own grouping |
| `expected_reading`, `forbidden_reading` | the right reading, and the wrong one, in words |

The report gives the share of cases the card **touches**, and the share it gets **right**: a flagged rule is one of
the case's `rules`. It also counts the cases by `grounded`. A case is evidence, never an approval: nothing in it
changes your rules.

## Measuring the correction finder: `--finder FILE`

A JSON-lines file of `{"text": "...", "correction": true}` or `false`. The report gives the finder's precision (how
many of the messages it calls corrections are corrections) and recall (how many of the corrections it finds).

## The report

`--json` prints the report as JSON, with these fields:

- `units`: `misread`, `clean`, `corrections`;
- `coverage`, `false_touch`: each `{p, lo, hi}`;
- `skill`: `{value, lo, hi}`;
- `rules_per_message`: `misread`, `clean`;
- `nulls`: `base` and `matched`, each with the same fields; `matched` adds `rules`, `drawn_from` and `seed`;
- `split`: `date`, `in_sample`, and, with a split, `rules_left_off` and `undated_left_out`;
- `card_rules`;
- `silent`, with `--show`;
- `cases`, with `--cases`;
- `finder`, with `--finder`.
