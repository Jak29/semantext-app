---
version: alpha
name: Semantext
description: The local page of Semantext, which hands your rules for reading you to your AI coding assistant with every prompt. Quiet by design, in neutral greys, with one gold accent for what is yours or needs you.
colors:
  primary: "#e8b553"
  on-primary: "#1d1503"
  background: "#121211"
  surface: "#1b1b1a"
  raised: "#222220"
  line: "#2a2a28"
  line-strong: "#3b3b38"
  text: "#ececea"
  text-2: "#a6a6a0"
  text-3: "#80807a"
  danger: "#f0705f"
  primary-light: "#b9831c"
  primary-ink-light: "#8a5f0b"
  background-light: "#fafaf9"
  surface-light: "#f1f1ef"
  raised-light: "#ffffff"
  line-light: "#e6e6e2"
  line-strong-light: "#d3d3ce"
  text-light: "#1b1b19"
  text-2-light: "#5a5a55"
  text-3-light: "#6f6f69"
  danger-light: "#c2412d"
typography:
  headline:
    fontFamily: Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, Helvetica Neue, Arial, sans-serif
    fontSize: 32px
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: -0.015em
  count:
    fontFamily: Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, Helvetica Neue, Arial, sans-serif
    fontSize: 24px
    fontWeight: 600
    lineHeight: 1.2
    fontFeature: '"tnum"'
  body:
    fontFamily: Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, Helvetica Neue, Arial, sans-serif
    fontSize: 15px
    fontWeight: 400
    lineHeight: 1.55
  body-strong:
    fontFamily: Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, Helvetica Neue, Arial, sans-serif
    fontSize: 15px
    fontWeight: 600
    lineHeight: 1.55
  meta:
    fontFamily: Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, Helvetica Neue, Arial, sans-serif
    fontSize: 12px
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, Helvetica Neue, Arial, sans-serif
    fontSize: 12px
    fontWeight: 600
    letterSpacing: 0.08em
  mono:
    fontFamily: Cascadia Mono, SF Mono, Consolas, ui-monospace, monospace
    fontSize: 12px
    lineHeight: 1.65
rounded:
  key: 5px
  control: 8px
  card: 12px
  sky: 16px
  full: 999px
spacing:
  rail: 216px
  content: 840px
  content-wide: 1120px
  gutter: 64px
  gutter-mobile: 16px
  group: 40px
  header: 36px
  row: 12px
  inline: 8px
components:
  nav-item:
    textColor: "{colors.text-2}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: 7px
  nav-item-current:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    typography: "{typography.body-strong}"
  decision-card:
    backgroundColor: "{colors.surface}"
    borderColor: "{colors.primary}"
    rounded: "{rounded.card}"
    padding: 16px
  button:
    textColor: "{colors.text}"
    borderColor: "{colors.line-strong}"
    rounded: "{rounded.control}"
    height: 34px
    padding: 14px
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.control}"
    height: 34px
    padding: 14px
  input:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.text}"
    borderColor: "{colors.line-strong}"
    rounded: "{rounded.control}"
    height: 38px
    padding: 12px
  switch:
    backgroundColor: "{colors.line-strong}"
    rounded: "{rounded.full}"
    width: 34px
    height: 20px
  switch-on:
    backgroundColor: "{colors.text-2}"
  list-row:
    borderColor: "{colors.line}"
    padding: 12px
  section-label:
    textColor: "{colors.text-3}"
    typography: "{typography.label}"
  count-number:
    textColor: "{colors.text}"
    typography: "{typography.count}"
  sky:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.sky}"
    height: 440px
  popover:
    backgroundColor: "{colors.raised}"
    borderColor: "{colors.line}"
    rounded: "{rounded.card}"
    width: 360px
    padding: 16px
  toast:
    backgroundColor: "{colors.text}"
    textColor: "{colors.background}"
    rounded: "{rounded.full}"
---

# Semantext

The design of Semantext's page (`semantext/static/index.html`). The front matter holds the dark theme's colours, which
are the page's own, and the light theme's with a `-light` suffix.

## Overview

**"Teach your AI coding assistant how to read you, once. Semantext hands your rules to it with every prompt."** That
is the line the README leads with. Semantext works without being touched: a hook hands your rules to your AI with
every prompt. The page is where a person checks that it works, answers what needs them, sees their rules, and sees
what it did for them, counted.

**Why it looks like this.** The first version of the page was busy. It used nine hues to mean nine things and put a
blue tint on every surface, line and glow. A starfield sat behind everything. Each screen held six or seven sections,
each with a heading, a note and a lead. This version was rebuilt from design research, and every rule below comes
from it:

- **Colour only pops out when it is unique.** A hue is seen without effort only when few things carry it; many coloured
  elements act as noise against each other (Healey, preattentive processing,
  https://www.csc2.ncsu.edu/faculty/healey/PP/).
- **Neutral palettes, with one hue used on purpose.** The eye should not be assaulted by colour: one intense hue,
  chosen deliberately, marks what needs attention (Stephen Few,
  https://www.perceptualedge.com/articles/dmreview/intelligent_dashboard.pdf).
- **Everything shown competes for attention.** Information that is irrelevant or rarely needed lowers the visibility of
  what is needed (Nielsen Norman Group, aesthetic and minimalist design,
  https://www.nngroup.com/videos/aesthetic-and-minimalist-design/).
- **Things close together read as one topic.** Proximity groups; space between groups must be larger than space within
  them (Nielsen Norman Group, https://www.nngroup.com/articles/gestalt-proximity/).
- **Hierarchy comes from contrast, not from more styles.** Make one thing dominant by quieting the rest, with a few
  sizes, two weights and two or three text tones (Refactoring UI, as summarised in secondary sources).
- **A calm tool lives in the periphery.** It informs without demanding attention, and moves to the centre only when
  something needs you (Weiser and Brown, https://people.csail.mit.edu/rudolph/Teaching/weiser.pdf; Amber Case,
  https://caseorganic.com/post/principles-of-calm-technology/).
- **Show what matters first; let people ask for the rest.** Explanations and rarely used detail sit one click away
  (progressive disclosure, Nielsen Norman Group).

**Measured on the example data, Today before and after:**

| | before | after |
|---|---|---|
| words on the screen | 536 | about 180 |
| colour families in the page | 7, more in the canvas | 2: gold and red |
| groups | 9 | 4 |
| type sizes | many | 4 |
| height at 1360 × 1000 | 2,134px | fits, with two decisions waiting |

**The places.** Each answers one question:

- **Today**: is it working, and does anything need me?
- **Rules**: what will my agents follow, and where?
- **Agents**: who is working, and what is each told?
- **Decisions**: what needs my word?
- **Settings**: the switches and the connections.

Try a message opens from Rules, What an agent gets from Agents, and Every message from Today. Each has a back link.

**Critical files:**

- `semantext/static/index.html`: the whole page, one file with inline CSS and JS. It has no build step and loads
  nothing from the network. Its `:root` holds these tokens.
- `semantext/server.py`: the page's local API, under `/api/`.
- `README.md`: the product's words.
- `docs/deck.png`, `docs/rules.png`, `docs/agents.png`: screenshots of Today, Rules and Agents, on example data.

## Colors

**Neutral greys carry everything.** They have a slight warm bias, so the gold sits in them naturally, and no tint
runs through the page. The page follows the system's light or dark setting.

- **Primary, gold:** `#e8b553` dark, `#b9831c` light (`#8a5f0b` for text). It means one thing: yours, or needs you
  now. It marks a decision waiting, the Decisions count, your own rules, the live dot, an agent's open request on the
  map, and the one primary button on a form.
- **Danger, red:** `#f0705f` dark, `#c2412d` light. It is for something broken or false only: a broken rule file, a
  message that claims to be you, an answer not from you, a rule that did not go out.
- **Surfaces:** `background` for the page, `surface` for a decision card, the sky and hover, and `raised` for inputs
  and popovers.
- **Text:** three tones. `text` is for what you read, `text-2` for the line under it, and `text-3` for labels, times
  and notes.
- **Lines:** `line` for row rules, and `line-strong` for controls.

**The greyscale test:** with the colour taken out, the page must still read. Hierarchy lives in size, weight and tone,
and colour is never the only carrier of a meaning: every state also has words.

## Typography

System faces only, because the page loads nothing from the network: Segoe UI Variable Text, falling back to
system-ui; Cascadia Mono for the card and commands.

**Four sizes, each at least 25% from the next:**

| Size | Used for |
|---|---|
| 32px | the one headline on each screen |
| 24px | the counts on Today |
| 15px | everything you read |
| 12px | labels, times, notes and the line under a title |

**Two weights:** 400 for reading, 600 for headlines, titles, counts and labels.

**Labels** are 12px capitals at +0.08em in `text-3`: `WHAT IT DID`, `RECENT`, `ON RECORD`. Lead text stops at 66
characters wide.

## Layout

**The frame.** A rail on the left and one column, centred.

- **Rail (216px):** the name, the environment your agents read now as a small switcher under it, the four places, and
  Settings at the foot. The current place is on a `surface` background, at weight 600. Decisions shows its count in
  gold.
- **Column:** at most 840px wide, or 1120px for Rules, Agents, Every message, What an agent gets and Try a message.

**Rhythm:** each screen holds at most four groups, 40px apart, with 12 to 14px inside a group. Groups are set apart by
space and hairlines, not boxes. Only a decision card and the sky sit on a surface.

### Today

1. **The headline:** "Working", or "2 decisions need you", or "Connect your AI". Under it, one sentence: "Your rules
   went with 6 messages of yours today, to 2 agents."
2. **Decisions waiting**, up to three, as cards. A card shows the question, then `#4 · claude-code@book · 11 hours
   ago`, then its options as buttons, with the recommended one marked "recommended" in grey. Under the cards: "Or send
   `#4 1` to any of your AIs, as its own message."
3. **What it did:** three counts, each a number and a short line, such as "17 · messages of yours carried your rules".
   A count that went without its rule says so in red. The rest of the counts, and how they are counted, are behind "+
   All counts, and how they are counted".
4. **Recent:** the last five messages, one line each: `claude-code@app · your question · all 16 rules · 11 h ago`.
   Selecting a line opens the five steps behind it. "Every message" opens the full list.

The first time, before any AI is connected, Today holds the headline and three numbered steps, and nothing else.

### Rules

1. **The headline:** "Rules", with one sentence under it.
2. **The constellation** (see Components) and its legend, which lists only what the picture holds.
3. **Add a rule** in your own words, for every agent or one, with a gold Add. Under it, the rules as lists by where
   they apply: `IN DEFAULT`, `REVIEWER ONLY`, `EVERYWHERE`. Each line holds the statement, a gold dot when it is in
   your own words, and a switch. Selecting a line opens when it applies, where it came from, how often it was needed,
   its test, and Remove.
4. **Links:** Try a message · Edit the file · Undo the last change; and "+ Add suggested rules".

### Agents

1. **The headline:** "Agents", with "4 agents · 3 environments" under it.
2. **The map**, once there are two agents or two environments (see Components).
3. **Every agent**, one line each: the name, how it is known ("bound by you", "seen in its folder", "claimed"), and
   its cards and own rules. Selecting one opens its rules, its display name, its folder, and the ways to try a message
   to it or see what it gets.
4. **Links:** What an agent gets; and "+ Name an agent by its folder".

### Decisions

1. **The headline:** "Decisions", with "2 waiting. Your answer goes to the agent that asked, with its next prompt."
2. **Requests**, as full cards: the question, who asked and when, why it needs you, the earlier answer if the same
   question was answered before, the options, and a box for your own words. Under them, how to answer from chat.
3. **On record:** a search box, and every decision as a line: `#3 Add a rule to Default?`, then "claude-code@app asked;
   you answered Add, typed in chat, 11 hours ago.", and its state: delivered, read, waiting, withdrawn, or "not from
   you" in red.
4. **The switch** that tells your agents to ask here.

### Settings

Environment · Switches (tone, jokes, the inbox, the feed, hearing your prompts) · Connections · Recent changes,
folded. Each row is a label, one short grey line, and its control on the right.

### Narrow screens

Below 900px the gutters close to 28px and two columns stack. Below 720px the rail becomes a row of names across the
top, the three counts stack, and the gutters are 16px. Nothing scrolls sideways.

## Elevation & Depth

The page is flat. Surfaces step from `background` to `surface` to `raised`, and hairlines separate rows.

- **Shadows** are only for what floats: menus, popovers, the toast and modals.
- **No glow and no starfield.** The one light effect is a rule lighting up for a moment in the constellation when a
  real message carries it.
- **Motion** happens only when something real does: a rule lights and fades over 1.4 seconds. With reduced motion,
  nothing moves.

## Shapes

- **Corners:** 5px for keys, 8px for buttons and fields, 12px for cards and popovers, 16px for the sky, and fully
  round for switches and the toast.
- **Circles carry identity:** stars, agents, you, and the live dot. Filled means on; hollow means off.
- **Dashes mean "not settled":** the rings of the constellation, the zones of the map, relayed words (dashed), a
  tool's notices (dotted), and a name an agent only claims.

## Components

### The constellation

Your rules as structure, on Rules.

- **Rings are where a rule applies:** the centre ring holds the rules for everywhere, the next ring the active
  environment's, and the outer ring each agent's own, as an arc labelled "reviewer only". The rings are dotted
  hairlines, labelled in small capitals: `EVERYWHERE · 9`, `IN DEFAULT · 7`.
- **Colour is who wrote it:** grey for what came with Semantext; gold, larger, for your own words; a lighter grey for
  an agent's proposal you added. A hollow star is switched off, and a ringed one is kept with the message it was taught
  from.
- **Lines:** gold lines join your own rules in the order you added them, so the shape grows as you correct your AIs.
  A faint closed line joins the shared rules, since every full card carries them together.
- **Only the structure you have is drawn:** a ring with no rules is not there.
- **Pointing** at a star shows its statement; **selecting** one opens it, with its switch and Remove.

### The map

Your agents at work, on Agents.

- **Environments** are dashed zones, named in small capitals.
- **Agents** are grey dots in the zones they work in. A gold dot on one means it is waiting for your answer.
- **You** are the gold dot on the left. Tools are a small grey dot below you.
- **Lines:** your words and your answers in solid grey, relayed words dashed, tool notices dotted, and an agent's
  open request in gold, the one line that waits on you. A sender that claims to be you is red.

### Decision card

A `surface` card with a 3px gold edge on the left. It holds the question in 15px weight 600, the meta line in 12px, and
the options as buttons. The card is the one thing on Today allowed to claim attention.

### Counts

A 24px number in `text`, with a 12px line under it in `text-2`, three to a row. There are no boxes and no sparklines.

### Line

One thing per row: a hairline below, 12px of padding, the subject in `text`, a short description in `text-2`, the time
in 12px `text-3`, and a + that opens it in place.

### The five steps

Opened from a line: `WHO ASKED`, `WHOSE WORDS`, `WHICH RULES`, `LAYERS` and `SENT`, as labels on the left. On the
right, what happened and, in 12px, why.

### Controls

| Control | Look |
|---|---|
| Button | a 1px `line-strong` edge, 8px corners, 34px tall, `text`; the edge darkens on hover |
| Primary button | gold with dark text, at most one per form: Add, Bind, Create, Save, Try it |
| Link | `text-2`, underlined in `line-strong`, `text` on hover |
| Input | `raised`, a `line-strong` edge, 8px corners, 38px tall |
| Switch | 34 × 20px; off is `line-strong`, on is `text-2`, never gold |
| Disclosure | "+ All counts", "– All counts" in `text-2` |

**Focus:** a 2px gold outline, 2px out.

## Do's and Don'ts

**Do:**

- Keep one accent, gold, for what is yours or needs you, and red for what is broken. Nothing else is coloured.
- Pass the greyscale test: take the colour away and the page still reads.
- Keep at most four groups on a screen, set apart by space.
- Make one thing dominant on each screen: the status, or a decision waiting.
- Keep explanations one click away: a + to open, a line to select.
- Show only the structure that exists: no empty ring, no map with one agent, no count of nothing.
- Count only from Semantext's own records, and say how in the open detail.
- Keep it still unless something real happens.

**Don't:**

- Don't add a hue to tell categories apart. Use position, labels, weight or a dashed line.
- Don't tint surfaces, lines or text with a colour.
- Don't decorate: no starfield, glow, gradient or tinted border.
- Don't put a note under every heading, or two topics in one group.
- Don't show what was said. The feed never keeps a message.
- Don't claim what an agent did. A count says what was sent with a message, never that it was obeyed.
- Don't load anything from the network, or build markup from rule text with `innerHTML`.
