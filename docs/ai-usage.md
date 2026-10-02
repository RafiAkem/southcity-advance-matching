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

- Task:     §8 ai.py, §3.1–§3.2 sheets.py
  Prompt:   "Implement ai.py and sheets.py from SPEC §8 and §3.1–§3.2" (Claude Opus)
  AI output:payload() does all math; summarize() via openai SDK; sheets with formulas for H, TOTAL, KPIs
  Problem:  Gemini key gave 402 (prepaid credits depleted); WP column I was not loaded
  Fix:      switched provider by env only (router, gh/gpt-6-luna); added Advance.note for column I

- Task:     §3.3 app.py
  Prompt:   delegated to DeepSeek V4.1 Flash with the module API contract
  AI output:sidebar, KPI cards, status-colored WP table, match detail, unmatched, summary panel
  Problem:  used deprecated `use_container_width` (Streamlit warns it will be removed)
  Fix:      replaced with `width="stretch"`; checked in a browser: KPIs = §7, summary in Bahasa Indonesia
