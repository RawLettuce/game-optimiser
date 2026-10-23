# game-optimiser: project rules for Claude (23 Oct 2026)

Read DESIGN-BRIEF.md (the ask), DESIGN.md (the design) and ADAPTERS-RESEARCH.md (per setting tables) first. Matthew's standing rules in the matthew-dev-rules skill apply; this file adds the project specifics.

## State
- Design only so far. No code. Next step after Matthew's review: Milestone 0 (read only verification on the Bazzite PC, see DESIGN.md 13 and ADAPTERS-RESEARCH.md 3), then Milestone 1 in a cloud session.

## Rules for this repo
- Python 3.14 standard library only; no pip packages on the host. Own parsers for EE.cfg and Steam KeyValues with lossless round trip tests.
- Dry run by default, `--apply` to write, typed YES for localconfig.vdf. Back up every file before writing, verify sha256 after, one undo per run, census before and after. Refuse unreadable or unparseable files; never treat them as empty.
- Game must be closed to edit its files, Steam must be closed to edit localconfig.vdf. Never kill processes. No sudo anywhere; a root step, if ever needed, goes in scripts/root-steps.sh.
- Config files and Steam launch options only. No memory reading, injection or anything anti cheat could object to.
- Every fact in the docs carries a tag: [P] primary, [S] secondary, [V] verified on the PC with date, [U] unverified. Move a fact from [U] only after it is checked on the PC, and date it.
- Tests run in the cloud with fixtures (tests/fixtures); report the count ("41/41 green") before anything touches the PC.
- British spelling, no dashes as punctuation in documents, no Oxford commas.

## Known blockers from the cloud container (23 Oct 2026)
- These hosts are blocked here: wiki.warframe.com, steamcommunity.com, pcgamingwiki.com, docs.bazzite.gg, bo3.gg, forums.warframe.com, web.archive.org. GitHub raw works. Facts from the blocked hosts were taken from search engine quotations and are tagged [S].
