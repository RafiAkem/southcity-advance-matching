# AI coding assistant log (SPEC §11)

- Task:     §2, §4–§6 matcher.py
  Prompt:   "Implement matcher.py from SPEC §2, §4–§6" (Claude Opus via omp)
  AI output:loaders (header found by `Date` in column A), normalize, 3-pass match, status
  Problem:  none; smoke run matched all 15 rows and 15 unmatched credits on first run
  Fix:      -

- Task:     §7 test_match.py, requirements.txt, .env.example
  Prompt:   delegated to a DeepSeek V4.1 Flash subagent with the exact §7 table and the matcher API
  AI output:table-driven asserts for rows 8–22, totals, counts, traps T1–T6
  Problem:  none; `python test_match.py` passes
  Fix:      -
