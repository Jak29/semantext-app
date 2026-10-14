# Example: the writing desk

A complete Semantext environment for a small team that drafts and reviews documents together. It shows every state a
rule can be in:

| Rule | State | On the card? |
|---|---|---|
| `draft-is-for-comment`, `keep-the-voice`, `cuts-need-the-author` | written by you, stationary | yes |
| `summary-first` | written by you, labelled adaptive (a label only: Semantext never changes a rule by itself) | yes |
| `leave-headings` | learned from a correction, then tidied and pinned stationary, with the exact words kept | yes, marked `(learned)` |
| `american-spelling` | switched off (`enabled: false`) | no, but kept in the file |
| `bullet-everything` | undone (`archived: true`, with the time) | no, but kept in the file |

## Try it

```bash
semantext init
mkdir -p ~/.semantext/profiles/writing-desk
cp examples/writing-desk/SEMANTICS.yaml ~/.semantext/profiles/writing-desk/
semantext env use writing-desk
semantext card
```

On Windows PowerShell, use `$HOME\.semantext\profiles\writing-desk` for the folder.

The card shows the nine base rules, then five writing-desk rules: the switched-off and undone ones are left out. The
whole card is in [the card format](../../docs/card-format.md#the-whole-card-for-the-example).

## Make it yours

- Switch a rule on or off: `semantext toggle writing-desk.american-spelling`.
- Switch a rule's mode label between stationary and adaptive: `semantext pin writing-desk.keep-the-voice`.
- Teach it from a real correction: `semantext teach WORDS...`.
- Undo a rule: `semantext undo writing-desk.summary-first`. It is archived, and stays in the file.
- Edit statements on the page (`semantext serve`), or in the file itself (`semantext where` prints its path).
