# The security floor

What Semantext promises to refuse, each with one line of why and the tests that hold it. This is the floor: a release
that breaks any of these is not released. [SECURITY.md](../SECURITY.md) says what each part touches and the limits
Semantext states; this page is the list of refusals that are pinned by a test.

Every test named here is a test node id (`tests/<file>.py::<test>`). A test named with parameters runs every case. The
must-pass partners, which keep a refusal from refusing everything, sit beside these tests in the same files.

**How the list is checked, and how far.** `tests/test_security_floor.py` reads this page and the source of each named
test, never running it, and refuses a fixed list of patterns, written out in its docstring: a test that is missing or
not where pytest collects it, or whose name is removed or bound again; one switched off (`__test__` false, a Test
class with an `__init__` or `__new__`, an async def, a generator, a file calling `pytest.exit`); one marked to skip or
fail outright, by pytest's or unittest's marks in the forms it reads, or by a decorator of the same file naming one;
one parametrized over a literal empty list, or requesting a fixture that is; a skip or a return at its own top level;
and one with no assert or `pytest.raises` that can run, is not caught by an except, `contextlib.suppress` or a broad
`pytest.raises`, and does not have one fixed value. A test whose source can skip it in the forms it reads must be named on a `Skips:`
line under its property; read those lines for which promises rest, on a given machine, on a test that may not have
run there (a symbolic link needs a privilege on Windows; a hard link needs a volume that has them).

That check is a static reader of source, and can never be complete. For example, and the list is not complete, it
does not see a mark reached by subscript or `getattr`, a private pytest module, a same-file decorator that replaces or
wraps the function, a test deselected by the configuration (`addopts = --deselect ...`), a skip through a helper
imported from another module, a method of an object or a plug-in's fixture, marks added at collection, or a check
that can run but cannot fail for a reason its source does not show. A test written to evade it is out of its reach.
So the floor is also attacked by an independent reader each release.

**A named test is not always proved to pin its promise.** Removing the guard an item names, one guard at a time, was last
done for items 2 to 7, 9, 13 and 20 to 23. Items 1, 8, 10 to 12, 14 to 19 and 24 had no such run: their tests ran and
passed, and whether each fails without its guard is not measured. Items 25 to 30 name tests that were already there.

1. **The gate reader imports on Python 3.10: every regex in the package compiles there.**
   Why: one quantifier 3.10 does not know stopped the gate reader importing at all, on a supported Python.
   - `tests/test_provenance_round3.py::test_f1_no_pattern_in_the_package_needs_python_3_11`

2. **A forged or replayed act of the person's is unverified, and is never applied.**
   Why: the person's word is the one authority an agent cannot mint; an act with no span, evidence that is not the
   record's own, an old turn, or one record used for a second act would let an agent act as the person.
   - `tests/test_work_round4_acts.py::test_a_spanless_act_is_refused_by_every_reader`
   - `tests/test_work_round4_acts.py::test_evidence_that_is_not_its_records_own_is_unverified`
   - `tests/test_work_round4_acts.py::test_an_old_turn_is_not_an_act_now_whatever_the_evidence_says`
   - `tests/test_work_round4_acts.py::test_one_record_authorizes_one_act_whatever_turn_id_the_evidence_gives`
   - `tests/test_work_round4_acts.py::test_the_same_record_under_another_sha_string_is_not_a_second_use`

3. **A package calling itself built-in is an outside plug-in, with every guard on.**
   Why: a built-in is told apart by being the package's own code; a name anyone can choose must switch nothing off.
   - `tests/test_api02_round5.py::test_a_package_named_built_in_is_not_a_built_in`
   - `tests/test_api02_round5.py::test_list_never_shows_a_package_named_built_in_as_on_for_a_built_ins_name`

4. **A span offset past 2\*\*63 is unverified, and never stops a read.**
   Why: no file position holds it, and a read that raised on one planted line would stop every read of the store.
   - `tests/test_work_round4.py::test_an_absurd_span_offset_is_unverified_and_never_raises`

5. **A junction or link at the work store refuses every write, on every Python.**
   Why: a write through a link lands somewhere else; the check read `Path.is_junction`, which only Python 3.12 has,
   so on Python 3.10 and 3.11 a junction was written through.
   - `tests/test_work_authority.py::test_a11_a_junction_or_link_at_the_store_or_a_hard_link_at_the_log_refuses_every_write`
   Skips: `tests/test_work_authority.py::test_a11_a_junction_or_link_at_the_store_or_a_hard_link_at_the_log_refuses_every_write`
   skips its second half where no junction (Windows) or symbolic link (elsewhere) can be made; a junction needs no
   privilege, so on Windows it runs.

6. **A time ending in Z is read as UTC on Python 3.10.**
   Why: `datetime.fromisoformat` takes a Z only from 3.11, so on 3.10 every act of the person's was undecidable and
   every verdict unfound.
   - `tests/test_times_ending_in_z.py::test_a_transcript_time_ending_in_z_is_read_as_utc`
   - `tests/test_times_ending_in_z.py::test_a_verdict_time_ending_in_z_is_read_as_utc`
   - `tests/test_times_ending_in_z.py::test_the_stand_in_refuses_a_z_as_python_3_10_does`

7. **A requests file that is a link of any kind, or that sits in a closed place, is not read.**
   Why: a `requests.jsonl` hard-linked to any readable file was shown as that agent's cards.
   - `tests/test_api02_round5.py::test_a_requests_file_that_is_a_hard_link_is_not_read`
   - `tests/test_api02_round5.py::test_a_requests_file_that_is_a_symbolic_link_is_not_read`
   - `tests/test_api02_round5.py::test_a_requests_file_in_a_closed_place_is_not_read`
   Skips: `tests/test_api02_round5.py::test_a_requests_file_that_is_a_symbolic_link_is_not_read` skips on Windows
   without the privilege to make a symbolic link, so there the link arm rests on
   `tests/test_api02_round5.py::test_a_requests_file_that_is_a_hard_link_is_not_read`, which needs no privilege and
   skips only on a volume with no hard links.

8. **A write whose referer is a plug-in's page module is refused.**
   Why: a page module runs with the page's reach; a change it makes from a module's own request must not pass as the
   person's.
   - `tests/test_api02_round5.py::test_a_write_whose_referer_is_a_plug_in_module_is_refused`

9. **An outside plug-in reads nothing until the closures are named.**
   Why: with no closed places named, the check closed nothing, so a plug-in could read anywhere the person keeps
   files; now every path is closed to it until they are named, and it cannot be turned on before.
   - `tests/test_registry.py::test_no_closures_named_closes_everything_to_a_plug_in`
   - `tests/test_registry.py::test_no_sources_file_is_closures_unknown`
   - `tests/test_registry.py::test_closures_that_cannot_be_known_close_everything`
   - `tests/test_registry.py::test_enable_refuses_until_closed_places_are_named`

10. **The card hook imports no process or network module, and no plug-in code.**
    Why: the hook runs on every message; it reads and prints, and must not be able to start a process, open a
    connection, or load a plug-in.
    - `tests/test_registry.py::test_the_hook_imports_no_process_or_network_module`
    - `tests/test_registry.py::test_the_hook_imports_a_pinned_set_and_no_registry`

11. **A plug-in is turned on only by the person typing its name back, at an interactive console.**
    Why: what is on is the person's act, like answering; an agent's shell, or no console, is refused.
    - `tests/test_registry.py::test_enable_refuses_in_an_agents_shell`
    - `tests/test_registry.py::test_enable_refuses_without_a_console`
    - `tests/test_registry.py::test_enable_refuses_unless_the_name_is_typed_back`

12. **A plug-in name two packages declare loads neither.**
    Why: which of the two runs must never be a guess; before, the command line took the first and the loader the
    last.
    - `tests/test_registry_audit.py::test_a_key_declared_by_two_packages_loads_neither_and_names_both`

13. **A document a place serves lies, as it leads now, inside a named root and outside every closed place.**
    Why: the path comes from plug-in code; a link that leads out, a hard link to a closed file, a span of one, or the
    Windows `\\?\` spelling of one must not be served.
    - `tests/test_doc_route.py::test_a_link_inside_a_root_that_leads_out_is_refused`
    - `tests/test_api02_round2.py::test_a_hard_link_to_a_closed_file_is_refused`
    - `tests/test_api02_round2.py::test_a_span_of_a_closed_file_is_refused`
    - `tests/test_api_v02.py::test_a_file_written_with_the_long_path_prefix_is_closed`
    Skips: `tests/test_doc_route.py::test_a_link_inside_a_root_that_leads_out_is_refused` where no junction (Windows)
    or symbolic link (elsewhere) can be made, `tests/test_api02_round2.py::test_a_hard_link_to_a_closed_file_is_refused`
    on a volume with no hard links, and `tests/test_api_v02.py::test_a_file_written_with_the_long_path_prefix_is_closed`
    everywhere but Windows, the one system whose paths have that prefix.

14. **What a plug-in gives back is taken as plain values, without running its code on the caller's thread.**
    Why: a `str` subclass's own methods would run outside the budget, and could hold or crash the server.
    - `tests/test_api02_round3.py::test_a_str_subclass_from_resolve_is_refused_without_running_its_code`
    - `tests/test_api02_round3.py::test_a_plug_in_attribute_of_a_str_subclass_is_bad`

15. **A plug-in's answers and calls are capped.**
    Why: one plug-in must cost only its own part of the page: never a 100 MB answer, and never every thread.
    - `tests/test_registry_audit.py::test_problems_are_capped_in_count_and_length`
    - `tests/test_registry_audit.py::test_an_answer_over_the_size_cap_is_not_used`
    - `tests/test_api02_round5.py::test_threads_past_their_budget_never_pass_the_cap_however_many_plug_ins`

16. **A package's name is never printed with its control characters or escape sequences.**
    Why: printed raw, it could move the cursor or rewrite what the person reads at their console.
    - `tests/test_registry_audit.py::test_an_escape_in_a_package_name_is_not_printed`

17. **A base or a home is one folder to every reader and the card hook, or refused by all of them.**
    Why: the readers and the hook joined and judged paths their own ways, so one spelling was two folders: a full path
    inside the base was read by the inbox and refused by the gates reader; " birch" was "base/ birch" to the inbox and
    "base/birch" to the gates reader; a base with a space, a tab or a `~` was read three ways; the hook gave a session
    the seat of a `..` home every reader refused; and with no base the inbox read no home and the others every full
    one. Now one rule, the path rule module, judges them all; the plug-in API page lists what it refuses.
    - `tests/test_sources_cards.py::test_the_inbox_places_and_gates_readers_judge_every_spelling_of_a_home_alike`
    - `tests/test_sources_cards.py::test_every_reader_judges_the_base_alike`
    - `tests/test_sources_cards.py::test_no_base_or_a_base_that_is_not_there_reads_no_home_in_any_reader`
    - `tests/test_sources_cards.py::test_a_base_under_tilde_is_the_users_own_home_and_never_another_users`
    - `tests/test_sources_cards.py::test_a_seats_file_any_reader_refuses_is_refused_by_every_reader_and_the_hook`
    - `tests/test_sources_cards.py::test_a_base_written_with_the_long_path_prefix_is_refused_as_a_prefix_not_a_stream`
    - `tests/test_sources_cards.py::test_a_problem_shortens_its_paths_and_keeps_its_reason_whole`
    - `tests/test_sources_cards.py::test_a_home_written_as_a_full_path_is_a_problem_inside_the_base_or_outside_it_as_the_other_readers_judge_it`

18. **A holder that asks again for the store's lock passes the gate where a waiter already stands.**
    With two writers the waiter goes next; with three or more the gate is first-come, not a queue.
    Why: without the gate, a writer in a tight loop could keep another out past its timeout, and every write of that
    one was refused.
    - `tests/test_store_append_checked.py::test_a_waiting_writer_goes_before_the_holder_asks_again`
    - `tests/test_store_append_checked.py::test_without_the_gate_the_holder_asking_again_wins_the_bare_lock`

19. **The work writer's seat checks fail closed: a seats setting that cannot be used refuses, never skips.**
    Why: a refused base once emptied the seat list, the writer took that for "no seats file", and a reviewer, a
    to_seat and an assignment then went through for any name. Now a seats file that is configured but cannot be used
    refuses each of those checks with its reason; only no seats configured at all is the mode without checks, and it
    is said aloud.
    - `tests/test_work_seats_unknown.py::test_to_seat_is_refused_when_the_seats_cannot_be_known`
    - `tests/test_work_seats_unknown.py::test_a_reviewer_is_refused_when_the_seats_cannot_be_known`
    - `tests/test_work_seats_unknown.py::test_an_assignment_is_refused_when_the_seats_cannot_be_known`
    - `tests/test_work_seats_unknown.py::test_a_seats_setting_that_cannot_be_used_refuses_every_seat_check`
    - `tests/test_work_seats_unknown.py::test_no_sources_file_at_all_is_the_one_mode_with_no_seat_checks_and_it_is_said`

20. **The Plug-ins tab only proposes and turns off: it never writes a setting, a reserved key, or a closures file.**
    Why: the page is reachable by anything that can send it a request; what it changes is the person's act at their
    console. It writes no setting (every change is a proposal, applied at the console), never a key of Semantext's own
    or of the closures (in any case), proposes nothing in a sources file that is also the closures file (its
    closures_file leads back to it) and offers no settings form there, and writes none of its own files through a
    link, a folder or a second hard link.
    - `tests/test_plugins_tab_attack.py::test_the_page_reaches_the_write_path_only_to_turn_a_plug_in_off`
    - `tests/test_plugins_tab.py::test_the_page_never_writes_a_setting`
    - `tests/test_plugins_tab_attack5.py::test_A5_a_reserved_key_is_refused_at_the_write_whatever_the_proposal_says`
    - `tests/test_plugins_tab_attack.py::test_A11_a_key_that_reads_as_a_reserved_one_is_refused`
    - `tests/test_plugins_tab_attack2.py::test_C1_nothing_is_changed_in_a_sources_file_that_is_the_closures_file`
    - `tests/test_plugins_tab_attack2.py::test_C1_no_settings_form_is_offered_on_a_sources_file_that_is_the_closures_file`
    - `tests/test_plugins_tab_attack.py::test_no_file_of_the_tab_is_written_while_it_has_a_second_name`
    - `tests/test_closed_names.py::test_a_plug_in_may_not_declare_a_closures_key_in_any_case`
    Skips: `tests/test_plugins_tab_attack.py::test_no_file_of_the_tab_is_written_while_it_has_a_second_name` on a
    volume with no hard links.

21. **Closures by name fail closed, and close every path an entry's own regex would.**
    Why: a names entry that cannot be read (an unknown form, a missing or extra field, an unusable literal) closed
    nothing before it was refused; a decomposed or marked spelling once opened a closed name. Now any such entry makes
    the closures unknown, and a path is closed when the field matcher (as given, NFC, NFD) or the entry's regex closes
    it.
    - `tests/test_closed_names.py::test_names_that_cannot_be_known_close_everything`
    - `tests/test_closed_names.py::test_a_closures_file_that_cannot_be_used_is_unknown`
    - `tests/test_closed_names.py::test_a_path_is_closed_whenever_its_entrys_regex_closes_it`
    - `tests/test_closed_names.py::test_the_fields_close_whatever_the_regex_closes_beyond_ascii`
    - `tests/test_closed_names.py::test_the_matcher_agrees_with_each_entrys_regex`

22. **A partial list of closed paths is never read as complete by a plug-in.**
    Why: a plug-in may read anywhere no rule closes; a lower bound read as the whole list would let through every
    closed file it does not name. Only the list under the key `closures_key` names, `closed_paths_complete` exactly true, and every known
    closed path in it, in a closures file of the closures-file format, opens anything to a plug-in; the serve hook,
    Work and the run-record reader read nothing meanwhile. The lower-bound readers (the card readers, which show your
    requests and change records, and the Places reader's root rule) read the list for what it lists. A context given
    to a plug-in and changed afterwards (its names included) closes every path, is never sealed anew, and each plug-in
    has its own copy. The seal stops accidents, not a hostile in-process plug-in.
    - `tests/test_closed_names.py::test_a_partial_list_is_never_read_as_complete`
    - `tests/test_closed_names.py::test_the_plug_in_side_needs_a_complete_list_that_agrees`
    - `tests/test_closed_names.py::test_the_same_file_named_as_the_closures_file_is_read_in_the_format`
    - `tests/test_closed_names.py::test_the_strict_view_closes_everything_while_the_list_is_incomplete`
    - `tests/test_closed_names.py::test_no_home_folder_is_closures_unknown_not_a_failure`
    - `tests/test_closed_names.py::test_a_read_context_whose_fields_are_set_afterwards_closes_every_path`
    - `tests/test_closed_names.py::test_a_made_read_context_is_never_sealed_anew`
    - `tests/test_closed_names.py::test_a_name_changed_after_its_context_was_made_closes_every_path`
    - `tests/test_closed_names.py::test_each_plug_in_gets_its_own_sealed_copy`

23. **A named root that is, or holds, a closed path is not walked by the Places reader.**
    Why: the closed check says nothing of an ancestor, and the Places reader reads files under a root without asking;
    a root that holds a closed folder (written through a link, or in its 8.3 short name, too) would be walked into it.
    - `tests/test_closed_names.py::test_a_root_that_holds_a_closed_path_is_refused`
    - `tests/test_closed_names.py::test_the_root_rule_agrees_with_the_reference`
    - `tests/test_closed_names.py::test_a_root_holding_a_closed_folder_written_through_a_link_is_refused`
    - `tests/test_closed_names.py::test_a_root_holding_a_closed_folder_written_in_its_short_name_is_refused`
    Skips: `tests/test_closed_names.py::test_a_root_holding_a_closed_folder_written_through_a_link_is_refused` where no
    junction or symbolic link can be made, and
    `tests/test_closed_names.py::test_a_root_holding_a_closed_folder_written_in_its_short_name_is_refused` everywhere but
    Windows, or where the volume gives no 8.3 short names.

24. **Nothing 1.3.0 read changes meaning, with one deliberate exception; every other change closes more.**
    The exception: a closures file in the closures-file format (schema `estate.closures/0`), new in 1.4, is read by
    that format's rules. Where its complete list is not supplied, it is read by the built-in card readers and the root
    rule as a lower bound (its known paths and names), and stays unknown to plug-ins and the strict view; and its path
    records are read as its paths, where 1.3.0 found them unreadable.
    Why: the closures-file format came after 1.3.0, and once its rules were applied to the sources file itself, a key
    of another tool (a "schema", a list of full paths) made known closures unknown; later, path records were read in
    the sources file, `\\.\C:\` as the drive, and a sources file with closed names and nothing else as known closures,
    each opening what 1.3.0 closed. The format (path records included) is read only in a closures file that says its
    schema; a sources file keeps 1.3.0's rules, and format-looking keys there (closed names among them) are only said.
    Closed names add closures and never by themselves make them known: for a plug-in and the strict view, known needs
    what 1.3.0 needed (a "closed" list, or a closures file read by its rules). An entry on a list in a form that cannot
    be compared closes every path, more than 1.3.0 did, and the page says so. A set of 1.3.0-shaped files gives the closures 1.3.0 gave, and a fixed set of paths (on
    Windows also as `\\?\` and `\\.\` forms) is judged in the plug-in, built-in and strict views as 1.3.0 judges them,
    checked against 1.3.0 itself; the exception is asserted case by case, and each file 1.4 closes more closes every
    path 1.3.0 closed.
    - `tests/test_closed_names.py::test_nothing_1_3_0_read_changes_meaning`
    - `tests/test_closed_names.py::test_the_recorded_1_3_0_meanings_are_what_1_3_0_gives`
    - `tests/test_closed_names.py::test_format_keys_in_the_sources_file_mean_nothing_and_are_said`
    - `tests/test_closed_names.py::test_path_records_are_read_only_in_a_file_that_says_the_schema`
    - `tests/test_closed_names.py::test_a_long_drive_prefix_is_read_as_the_drive`
    - `tests/test_closed_names.py::test_names_alone_never_make_the_closures_known`
    - `tests/test_closed_names.py::test_an_entry_that_cannot_be_compared_closes_every_path_and_is_said`
    - `tests/test_closed_names.py::test_a_sources_file_shaped_like_the_format_is_not_known_by_its_names`
    Skips: `tests/test_closed_names.py::test_the_recorded_1_3_0_meanings_are_what_1_3_0_gives` where git cannot run or
    the checkout holds neither the v1.3.0 tag nor its source commit (a shallow clone; CI fetches the whole history
    and compares with the tag), and
    `tests/test_closed_names.py::test_a_long_drive_prefix_is_read_as_the_drive` everywhere but Windows, and
    `tests/test_closed_names.py::test_an_entry_that_cannot_be_compared_closes_every_path_and_is_said` for a backslash
    form on a system where it is not a full path.

25. **Every spelling of a closed place is closed: a share, a device form, an NTFS alias, another name of the folder.**
    Why: a closed place's bytes can be named by a spelling no path comparison sees: `\\localhost\C$\...`,
    `\\?\UNC\`, `\\?\GLOBALROOT\`, `\\.\`, a stream suffix or trailing dot, or a mapped or subst drive.
    - `tests/test_closed_names.py::test_a_share_path_is_closed_while_only_names_are_closed`
    - `tests/test_closed_names.py::test_a_closed_name_is_refused_and_its_near_miss_is_not`
    - `tests/test_api02_round2.py::test_a_folder_reached_by_a_name_no_path_shows_is_closed_by_identity`
    Skips: `tests/test_closed_names.py::test_a_share_path_is_closed_while_only_names_are_closed` everywhere but Windows,
    and `tests/test_api02_round2.py::test_a_folder_reached_by_a_name_no_path_shows_is_closed_by_identity` where no such
    second name can be made.

26. **Answering is the person's act: a relayed approval is never the person's word.**
    Why: an answer decides what an agent may do. In a shell it needs a console and no agent's marks; in chat only a
    message the tool's own record says the person typed counts, so another agent's words, or pasted text, answer
    nothing, whatever they say; and an answer holding a key is refused and never kept.
    - `tests/test_chat_answers.py::test_only_a_message_the_tools_record_calls_the_users_answers_anything`
    - `tests/test_chat_answers.py::test_another_agents_message_answers_nothing_even_when_the_record_says_human`
    - `tests/test_chat_answers.py::test_pasted_text_that_mentions_requests_answers_nothing`
    - `tests/test_chat_answers.py::test_a_listed_key_in_a_typed_answer_is_refused_and_never_kept`
    - `tests/test_inbox_and_agents.py::test_the_cli_files_a_request_and_an_agent_cannot_answer_it`
    - `tests/test_inbox_and_agents.py::test_the_library_refuses_a_terminal_answer_from_an_agents_process`
    - `tests/test_adversarial_inbox.py::test_answer_is_refused_for_every_non_console_stdin`
    - `tests/test_feed.py::test_a_relay_that_names_itself_as_the_user_stays_another_agents_words`
    Skips: `tests/test_adversarial_inbox.py::test_answer_is_refused_for_every_non_console_stdin` skips its Windows-only
    kinds of stdin on other systems.

27. **The page answers only itself: another site's change, or another Host, is refused.**
    Why: any web page the person opens can send requests to a local port, and a rebound name can reach it as well.
    - `tests/test_claude_and_server.py::test_a_change_from_another_site_is_refused`
    - `tests/test_claude_and_server.py::test_a_request_for_another_host_is_refused`
    - `tests/test_adversarial_inbox.py::test_a_page_answer_needs_the_pages_own_origin`
    - `tests/test_feed.py::test_only_the_page_itself_reads_the_feed`
    - `tests/test_v2_page.py::test_every_route_answers_the_page_and_refuses_anyone_else`

28. **Over MCP no tool answers a request or changes a rule.**
    Why: an MCP client is an agent; a rule from one is only ever a proposal, and an answer is only ever the person's.
    - `tests/test_mcp.py::test_no_tool_answers_or_changes_a_rule`
    - `tests/test_mcp.py::test_a_rule_over_mcp_is_only_ever_a_proposal`
    - `tests/test_mcp.py::test_an_answer_reaches_the_asking_client_and_no_other`

29. **An agent reads, marks and withdraws only its own requests.**
    Why: another asker's answer read or marked is lost to the one who asked; withdrawn, it was never theirs to take back.
    - `tests/test_inbox_and_agents.py::test_only_the_asker_or_the_user_can_withdraw`
    - `tests/test_inbox_and_agents.py::test_answers_marks_only_its_own_askers_answers_read`
    - `tests/test_adversarial_inbox.py::test_an_unscoped_reader_does_not_swallow_other_askers_answers`

30. **A second name is not read: these readers refuse a hard-linked file.**
    Why: the closed check judges a path, and a hard link to a closed file has a path of its own (the judge does not see
    one, by design), so each reader must refuse it. This item pins the readers named here and in items 5, 7, 13 and 20;
    other places in the code refuse a second name without a test named on this page.
    - `tests/test_change_evidence.py::test_a_hard_link_is_never_read`
    - `tests/test_sources_change.py::test_a_changes_file_that_is_a_hard_link_is_not_read`
    - `tests/test_evidence_gitindex.py::test_a_git_file_a_missing_index_and_a_linked_index_are_unknown`
    - `tests/test_work_authority.py::test_a9_a_transcript_record_through_a_link_a_hard_link_or_a_bad_session_is_no_evidence`
    - `tests/test_v2_documents.py::test_a_hard_link_and_a_file_swapped_before_the_read_are_refused`
    - `tests/test_store_append_checked.py::test_a_hard_link_at_the_lock_or_its_gate_is_refused_and_the_other_file_is_untouched`
    - `tests/test_feed.py::test_the_inbox_lock_is_never_taken_on_what_stands_at_its_name`
    Skips: on a volume with no hard links, `tests/test_change_evidence.py::test_a_hard_link_is_never_read`,
    `tests/test_sources_change.py::test_a_changes_file_that_is_a_hard_link_is_not_read`,
    `tests/test_evidence_gitindex.py::test_a_git_file_a_missing_index_and_a_linked_index_are_unknown`,
    `tests/test_work_authority.py::test_a9_a_transcript_record_through_a_link_a_hard_link_or_a_bad_session_is_no_evidence`,
    `tests/test_v2_documents.py::test_a_hard_link_and_a_file_swapped_before_the_read_are_refused`,
    `tests/test_store_append_checked.py::test_a_hard_link_at_the_lock_or_its_gate_is_refused_and_the_other_file_is_untouched`
    and `tests/test_feed.py::test_the_inbox_lock_is_never_taken_on_what_stands_at_its_name`.
