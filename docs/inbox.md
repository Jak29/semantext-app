# The inbox

When your AI needs your decision or your permission, it files a request in your inbox instead of acting, and keeps
working on whatever does not need you. You answer when you have time: on your page, in your own terminal, or by sending
the request's number and your choice to any of your AIs as a message of its own (`#12 2`). Your answer reaches the AI
that asked with its next prompt, and stays on record. Semantext never runs anything for you.

## Switch it on

```
semantext feature inbox on
```

This adds one rule to the card of your active environment (`--env NAME` for another one):

> When you need my decision or permission, file it with `semantext ask` (a title, why it needs me, the options and your
> recommendation) and keep working on what does not need it. Act on it only after my answer reaches you. Never answer
> your own request; only my answer counts.

`semantext feature inbox off` takes the rule off again. The commands below work either way; the rule is what tells
your AI to use them.

## Three kinds of request

- **A decision:** a question with up to 9 options, perhaps with the one the AI recommends. You pick an option, add
  your own words to it, or answer in your own words alone.
- **A command:** a command for you to run yourself, what it does, how to undo it (or "cannot be undone"), and the folder
  to run it in, if that matters.
  - Semantext keeps the command exactly as written and never runs it.
  - It adds a second-look flag where the command may delete or overwrite, use the network, or ask for admin rights.
    No flag does not mean safe.
- **A rule the AI proposes:** `semantext teach` from an agent's own shell files one, since the words came through the
  agent, not from you. It reaches your card only if you add it:
  - as it is, kept as that agent's proposal, which the card says;
  - in your own wording, which replaces the agent's and is then your words;
  - or not at all.

A request is one kind, never two. Every request has a short title (up to 120 characters) and says why it
needs you. A request that looks like it carries a key, a token or a password, in any of its fields, is refused.

## For an AI: asking

```
semantext ask --title "Merge the release branch?" --why "It changes what users get" --question "Merge now, or wait for the review?" --option "Merge now" --option "Wait for the review" --recommend 2
semantext ask --title "Install the packages" --why "The tests need them" --command "pip install -r requirements.txt" --does "Installs the project's packages" --undo "pip uninstall -r requirements.txt -y"
```

- `semantext ask` prints the request's number, such as `[#12]`. Keep working on what does not need the answer, and act
  on the request only once the answer reaches you.
- **Who is asking:** Semantext works it out, with nothing named (see [Several agents on one inbox](#several-agents-on-one-inbox)).
  A name the agent states, with `--from NAME` or `$SEMANTEXT_AGENT`, is a claim, and shows as claimed.
- **Withdrawing:** `semantext close 12 --how "superseded by #14"`.
  - Only the agent that asked can withdraw it, or you at your own terminal.
  - A withdrawn request stays in the file, marked withdrawn, with who withdrew it. A withdrawal never counts as an
    answer.

## For you: answering

```
semantext inbox                      # what is waiting for you
semantext inbox --all                # answered and withdrawn requests too
semantext answer 12 2                # option 2
semantext answer 12 2 but only after the tests pass
semantext answer 12 "Not yet. Ask me again on Monday."
semantext answer 13 done             # a command you ran
semantext answer 13 wont             # a command you will not run
semantext answer 14 add              # add the proposed rule as it is
semantext answer 14 add Explain an error first. Fix nothing yet.   # add it in your own words
semantext answer 14 no               # do not add it
```

- After the choice, the rest is your own words, kept exactly. To answer in your own words alone, put them in quotes.
- A command takes `done`, or `wont` (also `"won't"`, quoted, since your shell reads the apostrophe), with your words if
  you like.
- On the page (`semantext serve`), each answer is a button: an option, Done or Won't do, or Add and Don't add for a
  proposed rule. A command has a Copy button, and there is a box for your words.
- A request takes one answer. The first answer or withdrawal stands.

### Answering in chat

Send the request's number and your choice to whichever AI you are talking to, **as a message of its own**:

```
#12 2                                  option 2
#12 2, but only after the tests pass   option 2, with your words after a mark
#12: Not yet. Ask me again on Monday.  your own words alone, for a question with no options
#13 done                               a command you ran (or #13 won't), words after a mark if you like
#14 add                                add the proposed rule as it is (or #14 no)
```

- **One answer per message, and nothing else in it.** The message's ends are trimmed (spaces, blank lines), and what is
  left must be that one line. A message with anything more, a second answer, a signature, a sentence before it, is not
  an answer, and the AI is told that nothing was taken. Answer two requests in two messages.
- **Your words after the choice follow a mark:** one of `. , ; :`, as in `#12 2, after lunch`. Without one, the line
  is a sentence: `#4 1 broken link` and `#1 2 tests failing` answer nothing. A dash and a closing bracket are not marks,
  since issue lists and ranges use them: `#4 1 - broken link` and `#12 2-3 tests failing` answer nothing either.
- **Words alone** (`#12: ...`) answer only a question with no options. A question with options takes its number, a
  command `done` or `won't`, and a proposed rule `add` or `no` with nothing after it (rewording one is the page's or the
  terminal's). The AI is told why when a form does not fit.
- **Why so strict:** the tool's record proves you typed or pasted a message, not that a line in it was meant as an
  answer. Pasted notes, an issue list or a ranked list of `#N` lines mention requests; only a message that is one
  answer in this form is taken as one. The limit that remains: one pasted line in exactly this form, sent as the whole
  message, is taken. A tracker's line `#4 1, broken link` sent alone, with request #4 waiting, records option 1 of #4
  with the words "broken link", and the AI is told what was recorded.
- Semantext takes a typed answer only when the message is your own: it must open as your words, **and** the tool's own
  record must say you typed it (Claude Code keeps one for every prompt). Another agent's message, a tool's notice, or a
  message with no record answers nothing, whatever it says. The AI is told either way: "The user answered in this
  message" with what was recorded, or that nothing was, and why.
- Your answer reaches the agent that asked, whichever chat you sent it in.

**Who can answer.** You can, from your own terminal, from the page, or from your own message in chat.
- `semantext answer` refuses in an agent's shell and without an interactive console.
- The page takes an answer only from itself.
- In chat, only the hook records an answer, and only as above.
- Every answer records where it came from, and `semantext inbox --all` and the page's On record list show it.
- An answer that holds a key, a token or a password of a known shape is refused, from anywhere. A long run shaped like
  a key no list names (32 or more letters and digits mixed, which includes a full commit hash) is kept as you wrote it,
  and shown on your page, but withheld as "(withheld)" from everything sent to an agent: the notes on its card,
  `semantext answers`, `semantext decisions` and the MCP tools. Give an agent a short commit hash instead.

This is a rule with a record, not a lock: see [what Semantext does not protect
against](../SECURITY.md#what-semantext-does-not-protect-against).

## How your answer reaches the AI

- **With Claude Code's hook,** every prompt starts with short inbox notes, before the card:
  - first, your answers that the AI has not read yet, to act on;
  - then the requests still waiting, not to be acted on yet.
  - Each part shows at most five, and the notes take at most 3,000 bytes. An answer too long to fit is counted, never
    cut, and the notes name the command that shows it.
- **For an AI:** `semantext answers` prints your new answers in full and marks them read. It reads only the answers to
  your own requests: the ones you filed, as this agent or in this session.
- **An agent without the hook** (Codex, freebuff, a local model) runs `semantext answers` to check.

## What you have decided: the register

Every request you answered or that was withdrawn stays on record, with your words, when, and how you answered. Agents
can look there before they ask:

```
semantext decisions                 # the newest 20
semantext decisions release branch  # those holding all these words
```

Over MCP, the `decisions` tool does the same. On the page it is the On record list under Decisions, with a search box.

When an agent asks the very question you answered before (the same question with the same options), the request is
filed all the same, and both you and the agent are shown the earlier answer beside it. It is never used for the new
one: an answer holds for what was offered when you gave it, and "yes, push it" last week is not "yes" to this week's
push. The page offers "Answer the same again", which is your answer, given now.

## Several agents on one inbox

Semantext tells your agents apart by what it can see, so you need not name them. The first match wins:

1. **A folder you bound to a name:** `semantext agent bind reviewer --folder PATH`, from your own terminal. Every
   agent working in that folder is `reviewer`, shown as "bound by you".
2. **A name the agent states,** with `--from NAME` or `$SEMANTEXT_AGENT`: a claim, shown as claimed. It never gets
   the requests or answers of an agent bound or seen under that name, only those filed under the same claim.
3. **The tool and the project,** such as `claude-code@app`, shown as "seen". The tool comes from the hook or from the
   markers it sets in its agent's shell. The project is the folder's git root, or the folder itself (never your home
   folder), and two projects with the same folder name stay apart (`app`, `app-2`).
4. **`ai`,** for anything else.

Each agent then:
- files its requests as itself, with its session;
- sees only its own answers and waiting requests in the hook's notes;
- marks only its own answers read with `semantext answers`;
- is refused by `semantext answer`, since its shell is an agent's.

An answer reaches the agent that asked, in the session it asked from, even if you bind its folder in the meantime.
Where Claude Code gives the shell its session id, a command run in a subfolder is still the same agent, and an id
inherited in another project counts for nothing. `semantext agents` lists every agent, with its recent sessions.
Two agents that Semantext cannot tell apart and that state no name share `ai`.

## The file

Requests live in `inbox.jsonl` in your Semantext home (`~/.semantext`, or the folder named by `SEMANTEXT_HOME` or
`--home`). The file is append-only, with one event per line: a request, an answer, a withdrawal or a read. Nothing in
it is rewritten or deleted.

- A request's first answer or withdrawal stands. Anything after it is ignored.
- A damaged line is skipped, never fatal.
- Every write holds a lock, so agents filing at the same moment get different numbers, and a number is never reused.
- `semantext doctor` says how many requests are waiting for you and how many answers are unread.

Leave the file to Semantext. An answer written into it by hand came from neither your terminal, your page nor your own
message, and any answer whose record names none of them is labelled "not from the user" wherever it shows.
