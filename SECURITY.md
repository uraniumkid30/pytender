# Security policy

Do not report suspected security vulnerabilities in public issues. Use the repository's private security advisory mechanism.

MoneyTender never needs to log API keys. Provider implementations should redact credentials, set finite timeouts, reuse clients/connections, validate HTTPS endpoints, and avoid embedding secrets in exception messages or provenance metadata.

Financial correctness issues that can produce materially wrong amounts should be treated with the same urgency as security defects.
