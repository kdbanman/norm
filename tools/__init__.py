"""Developer-only tooling for the norm repo.

NOT part of the shipped product: this package lives outside ``src/`` and is
excluded from the wheel (see ``[tool.hatch.build.targets.wheel]``). Nothing here
may become a ``norm`` subcommand — the product CLI surface is contractual
(REQ-GLOBAL-002). These are the recurring TDD-loop chores (a throwaway smoke
store; querying the requirements doc) given a durable home instead of being
re-derived as shell one-liners each session.
"""
