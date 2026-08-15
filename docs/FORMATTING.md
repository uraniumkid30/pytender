# Formatting and localization

Core formatting is deterministic and dependency-free via `SimpleMoneyFormatter`. It is appropriate for logs, tests, CLI output, and applications that specify separators explicitly.

Human localization is a separate concern from monetary arithmetic. Install `PyTender[babel]` and use `BabelMoneyFormatter` for CLDR-backed locale-aware output. Formatting never changes the stored amount and must never be parsed back as the canonical accounting representation.
