"""
StackWealth Planner evals — pytest-style cases organised into four layers:

    Layer 1  skill_math     deterministic skill output assertions (no LLM)
    Layer 2  tool_selection single-turn agent tool-call assertions
    Layer 3  e2e            multi-turn flow assertions on final PlanState
    Layer 4  regression     specific shipped-bug regressions

Run with `python -m stackwealth.evals.cli run` — see backend_py/evals/README.md.
"""
