# Publication checks

Run `python tools/check_publication.py .` from the repository root. Before Git initialization it examines candidate source files, excluding ordinary generated working directories. Inside a Git repository it examines the exact index blobs: use `git add` before the release check. An empty index is an empty publication candidate, not a successful audit of every untracked file.

The checker rejects tracked runtime data, private configuration paths, local overrides, generated build files, memory notes (the generic `memory/SCHEMA.md` is permitted), symlinks requiring review, submodules requiring separate review, unreadable/non-UTF-8 data and obvious private-key/credential patterns. Paths and rule names are reported; matching secret contents are not printed. A clean `.env.example` may be supplied as a template, but content checks still apply.

Additional private identifiers can be supplied with repeated `--deny-text` arguments. These values are not built into the public tool. The check is heuristic and does not prove the absence of every possible secret or confidential fact; review the staged diff and file list as well.

Run `python -m unittest tests.test_publication` for the checker regressions, including staged-versus-working-tree differences, forced tracked runtime data, standard private-key formats, binary data and symlink entries. The default application tests must use only deterministic offline providers and isolated temporary state.

The GitHub Actions workflow runs the test suite, this checker and an installed-package smoke test on Windows and Ubuntu for every push and pull request. Use the result of an actual run as release evidence, not the workflow definition.
