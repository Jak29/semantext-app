"""The reader, v0: a message read clause by clause, and what those readings advise for one act.

The design's spine is: your words -> readings -> the rule -> the act -> the gate -> the record. This module is the
second step. It is pure: no file, no network, no clock, nothing saved. It takes words and gives readings and advice.

ALLOWED is earned, never the default (r2, after Koinos's attack on r1 found 39 false ALLOWED in 12 families: a curly
apostrophe, a hold word not on the list, a hold two clauses away, a condition mid-clause, a later time it did not know,
a house rule read as permission, the clip). A list of hold words always misses one, so r2 runs the other way: a material
act is ALLOWED only when the whole message is read and plain (see `_plain_go`); anything the reader cannot place asks.

r3, after Orithises's attack on r2 (run, not traced: false ALLOWED in 8 families over 1,517 inputs, among them a
noun that opens a clause, "Postgres is down", and a hold with no hold word, "Publish it, I guess"): the reader NEVER
says ALLOWED for a material act. Reading English with patterns cannot be made safe enough to pass an act alone, and
the architecture never asked it to (the Gate never auto-approves). The most it says is ASK with covers=True ("your
words appear to say go", with the quote and any time word), which fills the ask in so the person confirms in one step.
ALLOWED is said only for a non-material act (an ordinary step in the work) that nothing holds.

Readings are ADVICE, never authority, in both directions. Advice can only make the gate's word stricter, never looser:
`tighten(gate_word, advice)` is the one place the two meet, and it returns the stricter of them. So a misreading that
says ALLOWED changes nothing the gate held, and a misreading that says ASK costs one question.

That asymmetry sets every judgement call below: when a cue is uncertain it is read toward a hold. A false hold costs
the person one answer; a false go costs an act they did not want.

What v0 does not do, stated so nobody relies on it:
- It reads cue words in English. It does not understand sentences: "I can't wait to ship it" reads as a hold.
- It does not know who is speaking. Relays and notices are told apart before this (sender.py, provenance.py).
- It does not know the time. "tomorrow" or "next week" on an act make it ASK: the reader cannot tell whether the time
  has come, and it never invents a date.
- A condition ("if the tests pass, publish") is not checked: it reads as a condition and asks.
- Reported speech ("he said publish it") reads as the speaker's own instruction.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .feed import scrub

MAX_CHARS = 20_000          # longer messages are read up to here, and the result says it was clipped
MAX_CLAUSES = 400
# The hint's shape and the words that spoil it (hint quality only: the hint never passes an act). A go for the hint is
# the verb, at most five plain words, an optional now-time word, and an optional thanks.
GO_SHAPE = re.compile(r"^[A-Za-z]+(?:\s+[A-Za-z]+(?:-[A-Za-z]+)?){0,5}\s*[.!]*$")
TAIL_COURTESY = re.compile(r",?\s*(?:thanks|thank you|please|cheers)\s*[.!]*$", re.I)
HINT_NOT = re.compile(r"\b(?:sometime|someday|some day|some point|due course|whenever|shortly|presently|eventually|"
                      r"soonish|eow|eod|yesterday|in a bit|in a while|down the line|at some point|later on|in time|skip|leave|let it be|scrap|nah|guess|whatever|up to you|your call|"
                      r"said|says|told|private|internal|draft|is|are|was|were|look|looks)\b", re.I)
BASE = {"publish", "release", "ship", "deploy", "post", "share", "upload", "push", "delete", "remove", "discard", "wipe",
        "purge", "erase", "send", "email", "mail", "forward", "submit", "pay", "buy", "spend", "purchase", "transfer",
        "subscribe", "download", "install"}
PUNCT = " \t\r\n.,;:!?'\"()[]{}-_/\\*&+#@~^|<>="

# The words that name an act, and whether the act is material (leaves the machine, spends, deletes or cannot be
# undone). Stems are prefixes on purpose ("delet" reads "deleting"); a stem that also catches an innocent word can
# only add a mention of the act, which reads toward a hold unless the clause is a plain instruction.
ACTS: dict[str, tuple[re.Pattern, bool, str]] = {
    "publish": (re.compile(r"\b(?:publish|releas|ship|deploy|post|share|upload)\w*", re.I), True,
                "publish or share it"),
    "push": (re.compile(r"\b(?:push|force-push)\w*", re.I), True, "push to a shared repository"),
    "delete": (re.compile(r"\b(?:delet|remov|discard|wip(?:e|ing)|purg|drop|erase|rm)\w*", re.I), True,
               "delete or discard"),
    "send": (re.compile(r"\b(?:send|sent|email|e-mail|mail|message|dm|reply|forward|submit)\w*", re.I), True,
             "send or submit"),
    "pay": (re.compile(r"\b(?:pay|paid|buy|bought|spend|spent|purchas|transfer|subscrib)\w*", re.I), True,
            "pay or spend"),
    "download": (re.compile(r"\b(?:download|install)\w*", re.I), True, "download or install"),
    "edit": (re.compile(r"\b(?:edit|fix|refactor|design|change|build|writ|implement|test)\w*", re.I), False,
             "change the work in place"),
}
MATERIAL = frozenset(k for k, (_, m, _) in ACTS.items() if m)

# Each kind, its label on the page, and whether it is a go, a hold or neither for the acts it names.
KINDS = {
    "instruction": ("INSTRUCTION", "go"),
    "keep": ("KEEP GOING", "go"),
    "assent": ("YES", "go"),
    "question": ("QUESTION", "soft"),
    "option": ("OPTION", "soft"),
    "condition": ("CONDITION", "soft"),
    "praise": ("PRAISE", "soft"),
    "withheld": ("HOLD", "hold"),
    "askfirst": ("ASK FIRST", "ask"),
    "yours": ("YOURS TO DO", "hold"),
    "note": ("NOTE", "none"),
}

# Time words, kept verbatim with the words as written. NOW-bound words limit a go; LATER words move it out of now.
TIME = re.compile(r"\b(?:till i give the say so|until i (?:give the say so|say so)|for now|going forward|from now on|"
                  r"tonight|today|this time|right now|tentatively|tomorrow|next week|this weekend|later)\b", re.I)
LATER = {"tomorrow", "next week", "this weekend", "later"}

# Clause boundaries: sentence ends, semicolons, and the joins where a second clause usually turns ("but", ", and",
# ", then", ", don't" ...). Splitting too much is safe: each piece is read on its own and the strictest reading holds.
SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+|,(?=\s*(?:but|and|then|so|don'?t|do not|never|not)\b)|(?<=\s)but(?=\s)", re.I)

YOURS = re.compile(r"\b(?:i'?ll|i will|i'?m going to|i am going to|let me)\b(?!\s+(?:know|see|leave|let)\b)"
                   r"|\bmyself\b|\bi'?d rather\b|\bi want to (?:do|handle)\b|\bleave (?:it|that|this) (?:to|for) me\b",
                   re.I)
ASKFIRST = re.compile(r"\b(?:ask (?:me )?(?:first|before)|without asking|check with me|run it by me|"
                      r"get my (?:ok|okay|word|approval)|wait for my)\b", re.I)
KEEP_ON = re.compile(r"\b(?:don'?t|do not|never) (?:stop|wait|pause)\b|\bkeep going\b|\bcarry on\b", re.I)
HOLD = re.compile(r"\b(?:hold off|hold on|hang on|don'?t|do not|not yet|not now|no need|wait|stop|park|pause|shelve|"
                  r"never|not|no|nope|nothing|cancel|undo|scratch that|forget it|instead|rather than|except|"
                  r"forbidden|needs? my)\b", re.I)
QUESTION_OPEN = re.compile(r"^(?:who|what|where|when|why|how|which|can|could|should|would|is|are|do|does|did|will|"
                           r"shall|may|have|has)\b", re.I)
OPTION = re.compile(r"\b(?:maybe|perhaps|might|we should|we could|you could|i was thinking|i'?m thinking|i feel|"
                    r"what if|how about|or we|probably|ideally)\b", re.I)
CONDITION = re.compile(r"^(?:if|when|once|after|unless|as soon as|provided)\b|\bif\b", re.I)
PRAISE = re.compile(r"^(?:i (?:really )?(?:like|love)|love|great|nice|looks (?:good|great)|impressive|amazing|wow|"
                    r"perfect|excellent|brilliant|beautiful|this is (?:much |so |really )?(?:better|great|good|perfect))\b",
                    re.I)
ASSENT = re.compile(r"^(?:yes|yeah|yep|ok|okay|sure|go ahead|do it|sounds good|let'?s do (?:it|that)|agreed|approved)\b",
                    re.I)
KEEP = re.compile(r"^(?:carry on|keep going|continue|proceed|resume)\b", re.I)
IMPERATIVE = re.compile(r"^(?:please\s+)?(?:build|write|make|run|merge|add|update|go|start|create|finish|commit|"
                        r"move|rename|open|close|use|try|do)\b", re.I)


@dataclass(frozen=True)
class Reading:
    clause: str
    kind: str
    acts: tuple = ()
    time: str | None = None
    house: bool = False          # a standing house rule, not words in this message

    @property
    def label(self) -> str:
        return KINDS[self.kind][0]

    def to_dict(self) -> dict:
        return {"clause": scrub(self.clause), "kind": self.kind, "label": self.label, "acts": list(self.acts),
                "time": self.time, "house": self.house}


@dataclass(frozen=True)
class Advice:
    word: str                    # ALLOWED, ASK or BLOCKED: advice, never authority (see tighten)
    act: str
    rule: str
    why: str
    quote: str = ""
    bound: str | None = None     # a time word that limits the go, verbatim
    covers: bool = False         # the words appear to say go for this act now: a hint for the ask, never a permission

    def to_dict(self) -> dict:
        return {"word": self.word, "act": self.act, "rule": self.rule, "why": self.why, "quote": scrub(self.quote),
                "bound": self.bound, "covers": self.covers}


@dataclass
class Read:
    readings: list = field(default_factory=list)
    clipped: bool = False
    unreadable: bool = False     # letters outside the Latin script: a lookalike may be hiding a hold word

    def to_dict(self) -> dict:
        return {"readings": [r.to_dict() for r in self.readings], "clipped": self.clipped,
                "unreadable": self.unreadable}


QUOTES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "`": "'", "´": "'", "′": "'",
                        "“": '"', "”": '"', "–": "-", "—": "-"})


def normalize(text: str) -> tuple[str, bool]:
    """The text as the reader sees it: compatibility forms folded (NFKC), every apostrophe spelled ', invisible format
    characters (zero-width spaces and joiners) removed, "do n't" joined. And whether it holds letters outside the Latin
    script, which the reader cannot vouch for: such a message never earns ALLOWED for a material act."""
    t = unicodedata.normalize("NFKC", text).translate(QUOTES)
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Cf")
    t = re.sub(r"\b(do|does|did|is|are|was|ca|wo|should|could|would) n't\b", r"\1n't", t, flags=re.I)
    odd = any((ch.isalpha() and not ch.isascii()) or unicodedata.category(ch).startswith("M") for ch in t)
    return t, odd


def clauses(text: str) -> tuple[list[str], bool]:
    """The message cut into clauses, and whether it was clipped first."""
    t = text if isinstance(text, str) else ""
    clipped = len(t) > MAX_CHARS
    t = normalize(t[:MAX_CHARS])[0]
    out = [c.strip(" \t,") for c in SPLIT.split(t)]
    # a clause of no letters is kept when it holds anything but punctuation (an emoji can be a hold: "Publish it. 🛑")
    out = [c for c in out if sum(ch.isalpha() for ch in c) > 1 or c.strip(PUNCT)]
    if len(out) > MAX_CLAUSES:
        out, clipped = out[:MAX_CLAUSES], True
    return out, clipped


def acts_of(clause: str) -> tuple:
    return tuple(k for k, (rx, _, _) in ACTS.items() if rx.search(clause))


LEAD = re.compile(r"^(?:(?:please|now|then|and|so|also|just|ok|okay|yes|yeah|sure|go ahead and|you can|feel free to|"
                  r"you may|i want you to|can you|could you)(?:\s*,\s*|\s+))*", re.I)


def lead_acts(clause: str) -> tuple:
    """The acts a clause's own verb names: the act word must open the clause, after at most a few softeners
    ("please", "yes", "go ahead and"). A go covers a material act only this way, so "fix the release notes" covers
    fixing, never releasing."""
    rest = clause[LEAD.match(clause).end():]
    return tuple(k for k, (rx, _, _) in ACTS.items() if (m := rx.search(rest)) and m.start() == 0)


def time_of(clause: str) -> str | None:
    m = TIME.search(clause)
    return m.group(0) if m else None


def kind_of(clause: str) -> str:
    """One clause's kind. Order matters: the reservations and holds are tested first, so a clause that holds any of
    them is never read as a go."""
    c = clause.strip()
    if YOURS.search(c):
        return "yours"
    if ASKFIRST.search(c):
        return "askfirst"          # "without asking" too: read toward the hold, the safe side
    if KEEP_ON.search(c) and not acts_of(c):
        return "keep"              # "don't stop", "keep going": a go for the work in hand, naming no act
    if HOLD.search(c):
        return "withheld"
    if c.endswith("?") or QUESTION_OPEN.match(c):
        return "question"
    if CONDITION.search(c):
        return "condition"
    if OPTION.search(c):
        return "option"
    if PRAISE.match(c):
        return "praise"
    if ASSENT.match(c):
        return "assent"
    if KEEP.match(c):
        return "keep"
    if acts_of(c) or IMPERATIVE.match(c):
        return "instruction"
    return "note"


def read(text: str) -> Read:
    """The message read clause by clause."""
    cs, clipped = clauses(text)
    odd = normalize(text[:MAX_CHARS])[1] if isinstance(text, str) else False
    out, named = [], []
    for c in cs:
        k, acts = kind_of(c), acts_of(c)
        # A hold that names no act ("Publish it, not now"; "Push it. Thanks. Don't.") holds every act named before it
        # in the message. It can only add a hold, so reading it this way is the safe side.
        if not acts and KINDS[k][1] in ("hold", "ask"):
            acts = tuple(named)
        named += [a for a in acts if a not in named]
        out.append(Reading(c, k, acts, time_of(c)))
    return Read(out, clipped, odd)


def read_rules(statements) -> list:
    """A space's standing house rules, read the same way and marked as house rules. A house rule can only add a hold:
    one that names an act is read as a hold if it holds, and as ask-first otherwise ("Publishing needs my approval",
    "No pushing to main"), never as a go. One that names no act adds nothing."""
    out = []
    for s in statements or []:
        for r in read(str(s)).readings:
            held = KINDS[r.kind][1] in ("hold", "ask")
            if r.acts:
                out.append(Reading(r.clause, r.kind if held else "askfirst", r.acts, r.time, house=True))
                if not any(a in MATERIAL for a in r.acts):   # "Nothing leaves the building": "build" is not its act
                    out.append(Reading(r.clause, "askfirst", tuple(a for a in ACTS if a in MATERIAL), r.time,
                                       house=True))
            elif held:      # "Hold everything": holds every act
                out.append(Reading(r.clause, r.kind, tuple(ACTS), r.time, house=True))
            else:           # "Nothing goes to GitHub without me", "Keep main untouched": ask first for every material act
                out.append(Reading(r.clause, "askfirst", tuple(a for a in ACTS if a in MATERIAL), r.time, house=True))
    return out


def _quote(r: Reading) -> str:
    return r.clause.rstrip(".!? ")


# What may stand beside a go and leave it plain: a courtesy, praise, or a yes or keep-going naming no act.
COURTESY = re.compile(r"^(?:thanks?|thank you|thx|cheers|ta|please|cool|great|nice|perfect|awesome|lovely|brilliant|"
                      r"good|fine|ok|okay|sure|yes|yeah|yep|right|done)(?:\s+(?:you|so much|a lot|very much|again|then))?"
                      r"[\s!.]*$", re.I)
# Words in a go clause that move or bound it in a way the reader cannot check: a condition, a later or named time, an
# alternative, an exception, a sequence. Any of them leaves the go unplain, and the act asks.
DEFER = re.compile(r"\b(?:unless|once|when|whenever|after|before|until|till|if|or|either|except|instead|rather|only|"
                   r"provided|soon|later|eventually|tomorrow|next|every|weekend|week|month|year|hour|minute|day|"
                   r"morning|afternoon|evening|noon|midnight|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
                   r"january|february|march|april|may|june|july|august|september|october|november|december|"
                   r"on|at|by|then|first|second|again|meanwhile|depending|assuming|provided|whether)\b|\d|\bpm\b|\bam\b",
                   re.I)
NOW = re.compile(r"\b(?:until i (?:give the say so|say so)|till i give the say so|for now|right now|this time|"
                 r"going forward|from now on|tonight|today|now)\b", re.I)


def _no_tail_courtesy(s: str) -> str:
    """s without a closing "thanks", "please" ... (a string check, not a regex: Orithises found the regex form
    quadratic on a long run of tabs, 19,000 tabs took 7.9 s)."""
    t = s.rstrip(" \t\r\n.!")
    low = t.lower()
    for w in ("thank you", "thanks", "please", "cheers"):
        if low.endswith(w) and (len(low) == len(w) or not low[-len(w) - 1].isalnum()):
            return t[:-len(w)].rstrip(" \t,")
    return s


def _plain_go(r: Reading, act: str) -> bool:
    """A go clause that plainly instructs this act now: the act is its own verb, and nothing in it moves or bounds it
    beyond a now-time word."""
    return (KINDS[r.kind][1] == "go" and act in lead_acts(r.clause)
            and not DEFER.search(NOW.sub(" ", r.clause[LEAD.match(r.clause).end():])))


def _plain_offer(offer: str) -> tuple:
    """The one material act a plain offer names ("Shall I publish the release?"), or () when the offer is not plain:
    more than one clause or act, an alternative, a hold, a condition or a later time. A bare yes binds only to a plain
    offer; to anything else it asks."""
    got = read(offer)
    if len(got.readings) != 1 or got.clipped or got.unreadable:
        return ()
    r = got.readings[0]
    acts = [a for a in r.acts if a in MATERIAL]
    verb = re.sub(r"^(?:shall|should|can|could|may|do you want|want)\s+(?:i|me to|we)\s+", "", r.clause, flags=re.I)
    if not acts or acts[0] not in lead_acts(verb):
        return ()
    if len(acts) != 1 or r.kind not in ("question", "instruction") or HOLD.search(r.clause) or OPTION.search(r.clause):
        return ()
    if DEFER.search(NOW.sub(" ", r.clause)):
        return ()
    return (acts[0],)


def advise(readings, act: str, offer: str | None = None, house=()) -> Advice:
    """What the words advise for one act. `readings` is a Read (from read()) or a list of readings; `house` the space's
    house rules (from read_rules). `offer` is the agent's last offer: a bare yes binds to a plain one-act offer and
    covers that act and nothing else.

    A material act is ALLOWED only when it is earned: a plain go for it (the act is the clause's verb, nothing moving
    or bounding it but a now-time word), no hold, ask-first or soft reading of it anywhere, every other clause of the
    message a courtesy or one naming other acts, and the whole message read (not clipped, no letters the reader cannot
    vouch for). Anything else asks, or is blocked by a hold."""
    if act not in ACTS:
        raise ValueError(f"unknown act {act!r}; known: {', '.join(ACTS)}")
    whole = readings if isinstance(readings, Read) else Read(list(readings))
    rs = list(whole.readings)
    offered = _plain_offer(offer) if offer else ()
    loose_yes = False
    if offer:
        new = []
        for r in rs:
            if r.kind == "assent" and not r.acts:
                if offered:
                    r = Reading(r.clause, r.kind, offered, r.time, r.house)
                else:
                    loose_yes = True
            new.append(r)
        rs = new
    rs += list(house)
    about = [r for r in rs if act in r.acts]
    bad = next((r for r in about if KINDS[r.kind][1] == "hold"), None)
    first = next((r for r in about if r.kind == "askfirst"), None)
    goes = [r for r in about if KINDS[r.kind][1] == "go"]
    if bad and goes:
        return Advice("ASK", act, "conflict-restrictive",
                      "Your words both allow and forbid it: the stricter reading holds, and the conflict comes back "
                      "to you.", _quote(bad))
    if bad:
        if bad.kind == "yours":
            return Advice("BLOCKED", act, "owner-reserved-action",
                          "You said you will do this yourself: the agent may prepare it, not do it.", _quote(bad))
        return Advice("BLOCKED", act, "house-rule" if bad.house else "withheld-stays-held",
                      "Held" + (f" ({bad.time})" if bad.time else "") + ".", _quote(bad))
    if first:
        return Advice("ASK", act, "house-rule" if first.house else "ask-first",
                      "You said to ask first: held, and you are asked, whatever else was said.", _quote(first))
    soft = next((r for r in about if KINDS[r.kind][1] == "soft"), None)
    if soft:
        rule = {"question": "question-not-instruction", "praise": "sentiment-not-authority",
                "condition": "condition-not-checked"}.get(soft.kind, "suggest-not-require")
        return Advice("ASK", act, rule, f"You mentioned it as {soft.label.lower()}, which is not a go.", _quote(soft))
    if act not in MATERIAL:
        go = goes[0] if goes else None
        return Advice("ALLOWED", act, "your-words-cover-it" if go else "standing-discretion",
                      "Your words cover it." if go else "Not a material act: an ordinary step in the work.",
                      _quote(go) if go else "")
    if not goes:
        if loose_yes and act in acts_of(offer or ""):
            return Advice("ASK", act, "yes-binds-to-offer",
                          "Your yes answers an offer that is not one plain act, so it is not read as a go for this one.")
        return Advice("ASK", act, "material-acts-need-words",
                      f"To {ACTS[act][2]} needs your words, and these do not cover it.")
    plain = [r for r in goes if _plain_go(r, act) or (r.kind == "assent" and offered == (act,)
                                                        and not r.clause[ASSENT.match(r.clause).end():].strip(PUNCT))]
    go = plain[0] if plain else goes[0]
    if len(plain) != len(goes):
        later = next((r.time for r in goes if r.time and r.time.lower() in LATER), None)
        return Advice("ASK", act, "time-kept-verbatim" if later else "go-not-plain",
                      f'Your words set a later time ("{later}"); the reader cannot tell whether it has come.' if later
                      else "Your words name it, but not as a plain go for now (a condition, a time, an alternative or "
                           "a mention): asked.", _quote(go))
    if whole.clipped or whole.unreadable:
        return Advice("ASK", act, "whole-message-not-read",
                      "Part of your message was not read (too long, or letters the reader cannot vouch for).",
                      _quote(go))
    stray = next((r for r in whole.readings if not r.acts and r.kind not in ("praise", "assent", "keep")
                  and not (r.kind == "note" and COURTESY.match(r.clause))), None)
    if stray:
        return Advice("ASK", act, "part-not-placed",
                      "Part of your message is not something the reader can place, so the go is not trusted alone.",
                      _quote(stray))
    # The hint itself is strict: the whole message is the go and courtesies only, with no hold, deferral, option or
    # condition word anywhere, and the verb in its plain base form ("Publish", not "Published", "Postgres", "Post-").
    rest = [r for r in whole.readings if r.clause != go.clause]
    words = NOW.sub(" ", " ".join(r.clause for r in whole.readings))
    lead = go.clause[LEAD.match(go.clause).end():]
    base = re.match(r"([A-Za-z]+)(?=$|[\s.,!;:?])", lead)
    shaped = GO_SHAPE.match(_no_tail_courtesy(lead)) or (go.kind == "assent" and offered == (act,))
    if (any(not ((r.kind == "praise" and len(r.clause.split()) <= 3)
                 or (r.kind in ("note", "assent") and COURTESY.match(r.clause))) for r in rest)
            or not shaped or HINT_NOT.search(words)
            or HOLD.search(words) or DEFER.search(words) or OPTION.search(words) or CONDITION.search(words)
            or not ((base and base.group(1).lower() in BASE) or (go.kind == "assent" and offered == (act,)))):
        return Advice("ASK", act, "go-not-plain",
                      "Your words name it, but not plainly enough to fill the ask in: say it again, or answer the ask.",
                      _quote(go))
    # r3 (Orithises's attack on r2, run: false ALLOWED in 8 families over 1,517 inputs): words alone never pass a
    # material act. The best the reader says is that your words appear to cover it, which fills the ask in for you.
    return Advice("ASK", act, "your-words-appear-to-cover-it",
                  (f'Your words appear to say go within "{go.time}". ' if go.time else "Your words appear to say go. ")
                  + "Words alone never pass this act: confirm it.", _quote(go), bound=go.time, covers=True)


SEVERITY = {"ALLOWED": 0, "ASK": 1, "BLOCKED": 2}


def tighten(gate_word: str, advice: Advice) -> str:
    """The gate's word, made stricter by the reader's advice and never looser. An unknown gate word fails closed."""
    g = SEVERITY.get(gate_word)
    if g is None:
        return "BLOCKED"
    return max(gate_word, advice.word, key=lambda w: SEVERITY[w])


# Rules under which the person's words HOLD an act (they hold, reserve, ask first, question, offer it as an option,
# praise it, condition it, defer it or conflict on it). The others say only that the words do not cover it, or appear
# to: those leave the decision to the gates.
HOLDING = frozenset({"conflict-restrictive", "owner-reserved-action", "withheld-stays-held", "house-rule", "ask-first",
                     "question-not-instruction", "sentiment-not-authority", "condition-not-checked",
                     "suggest-not-require", "go-not-plain", "time-kept-verbatim", "yes-binds-to-offer",
                     "part-not-placed", "whole-message-not-read"})


def held_by_words(words, acts, offer=None, house=(), memo: dict | None = None) -> dict | None:
    """For a tool call of these acts: the first act the person's words hold, as {"act", "word", "rule"} (no quote: the
    words stay out of anything the model or the record sees), or None when the words hold none of them. Only ever adds
    a hold; a go in the words releases nothing."""
    if not acts or not isinstance(words, str) or not words.strip():
        return None
    # `memo` (one per decision): the words are read once and each act advised once, however many calls a turn holds
    # (Orithises, re-attack on the wiring's fixes: 2,000 calls re-read 16 KB of words 2,000 times, 60 s).
    memo = {} if memo is None else memo
    if "read" not in memo:
        memo["read"] = read(words)
    for a in acts:
        if a not in ACTS:
            continue
        if a not in memo:
            adv = advise(memo["read"], a, offer=offer, house=house)
            memo[a] = {"act": a, "word": adv.word, "rule": adv.rule} if (adv.word in ("ASK", "BLOCKED")
                                                                         and adv.rule in HOLDING) else None
        if memo[a]:
            return memo[a]
    return None
