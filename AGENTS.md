# Coding agent handoff

Read `README.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/ARCHITECTURE.md`, `docs/API_CONTRACT.md`, and `docs/SECURITY.md` before editing.

## Priorities

1. Preserve the **VLA-only task policy**: no high-level rule-based fallback or existing robotics skill as an alternative decision-maker during benchmarks.
2. Implement milestone P0 first, then P1; add learned models only after typed observation/action safety contracts work.
3. Do not claim mock API or controller scaffold constitutes a tested physical deployment.
4. Use proper action frame, named joints, units, normalization statistics and timestamps; fail closed.
5. Keep model adapters pluggable; do not put model-specific prompt/image rules into the ROS bridge.
6. Separate inference and actuation. Never enable live actuation in tests.
7. Prefer ROS 2 Humble Python package and compatible LeRobot releases; pin tested deps. Containers allowed for incompatible backend deps.
8. Keep repository public-safe. No credentials, real endpoint IPs, data captures, private identifiers or weights.
9. Use normal merge commits (no rebase/force push) when integrating work. Prefer small PRs with explicit verification commands and test outcomes.
10. Update docs on architectural changes and include tests for error and disconnect paths.

## Immediate assignment

Implement WP01: make typed validation, registry and dummy policy actually executable and covered by offline tests. Then WP02: ROS topic synchronization and dry-run end-to-end integration.

Current scaffold is an initial draft: TODOs are intentional; do not infer existence of trained ACT/Diffusion/π₀.₅ weights. Confirm current upstream APIs instead of assuming module paths or model version names.
