# First-user pass: making a second environment (fe70acd)

> **Status:** all five snags below were fixed in b795a0e.

*The user: a stranger who has the Default environment and wants a second one.*
- **The build:** Semantext 0.1.0 at fe70acd, wheel sha256 27df6268…9664.
- **The setup:** Windows 11 and Python 3.14, offline, in a fresh venv with a scratch home and a sandboxed profile.
- **The route:** the CLI as the README describes it, then the page in a browser on 127.0.0.1.

## What works now

- **The page's + works.** The **+** beside the gear opens "A new environment".
  - With a name that matches a pack ("Studying"), the pack's suggestions appear as you type, each with a ticked box.
  - Unticking one is honoured: Studying kept the three rules left ticked, and not the fourth.
- **A name that matches no pack works on the CLI.** `env new` makes an empty environment, shows one idea from each
  pack, and says how to add them.
- **`env add ID [ID ...]` works.**
  - It adds suggestions to the active environment, or to the one `--env NAME` names.
  - The same IDs again add nothing, and it says so.
  - An unknown or missing ID is refused in one line.
- **The options work:** `--none` and `--pick` do what the help says.
- **A taken name is never overwritten.** A second "Cooking" became `cooking-2`.

## Snags, most important first

1. **"Profile" finds nothing.**
   - A new user may call these profiles. The data folder is `profiles/`, and the page's API uses `/api/profile`.
   - But the commands, the help and the page say only "environment", and `semantext profile` is an error.
   - **Fix:** accept `profile` as another name for `env`, and say "environments (profiles)" once in the top-level help and
     in the README.
2. **Switching by the title fails.**
   - `semantext env use Gardening` replies "not an environment name: 'Gardening'". Only `gardening` works, though the
     list shows both.
   - **Fix:** accept the title, ignoring case, when it names exactly one environment. Otherwise suggest the name ("did
     you mean gardening?").
3. **A name that matches no pack ends in an empty environment, with no next step.**
   - In the dialog, a name that matches nothing ("Baking") shows the four ideas, unticked, after a short pause.
   - Pressing Create without ticking one makes the environment with no rules of its own, and with no hint of what to do
     next.
   - **Fix:** after an empty environment is made, point to where rules are added.
   - **Corrected:** an earlier draft of this report said that nothing appeared for "Baking". That was inferred from the
     result: the dialog was not looked at between typing the name and pressing Create.
4. **The page cannot add suggestions to an environment that already exists.**
   - The Rules panel offers Teach and the three switches (match my tone, jokes, news), but not the packs' suggestions.
     On the CLI, `env add` gives them.
   - **Fix:** an "Add suggestions" list in the Rules panel.
5. **Two environments can share a title.**
   - `env new Cooking` twice made `cooking` and `cooking-2`, both titled "Cooking".
   - The page's switcher and its Rules tabs then show two identical "Cooking" entries, with no way to tell them apart.
   - **Fix:** title the second "Cooking 2", or say that Cooking already exists and how to switch to it.
