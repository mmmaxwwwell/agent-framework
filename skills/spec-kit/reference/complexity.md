# Complexity Tracking Enforcement

Spec-kit's plan template includes a Complexity Tracking table, but it's gated behind "Fill ONLY if Constitution Check has violations." The skill mandates that this table is actively maintained — not just at plan time, but during implementation. The constitution is only useful if violations are caught and justified, not silently ignored. This prevents agents from quietly over-engineering.

## Rules

1. **At plan time**: Any design decision that introduces an abstraction, interface, indirection layer, generic solution, or additional dependency beyond the simplest possible approach MUST either:
   - Confirm it doesn't violate any constitution principle, OR
   - Add a row to the Complexity Tracking table with: the violation, why it's needed, and why the simpler alternative was rejected

2. **At implementation time**: If an implementing agent needs to deviate from the plan — adding an interface the plan didn't call for, introducing a new dependency, creating an abstraction layer — it MUST:
   - Add a row to the Complexity Tracking table in `plan.md` before proceeding
   - Include a comment in the code referencing the justification

3. **The table format**:

   | Violation | Why Needed | Simpler Alternative Rejected Because |
   |-----------|------------|-------------------------------------|
   | SigningBackend interface (4 implementations) | Users need Yubikey + app key + mock signing | Direct implementation would duplicate sign-request flow 3× |
