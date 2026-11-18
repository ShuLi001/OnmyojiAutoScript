# Asset Snapshot Workflow Implementation Plan

**Goal:** Complete login -> courtyard -> inventory -> scan -> courtyard using existing OAS navigation and configuration.

**Architecture:** Reuse LoginService and GameUi. Register an inventory Page with two transitions. Save an atomic snapshot per config, device and configured login character; only a completed full scan establishes a baseline. An automatic subsequent run selects Recent and overlays observed quantities on the baseline.

**Constraints:** Keep the 73 OASX variable names and the removed eternal-divine-talisman template disabled. Match 95x70 material templates. Reset at most 3 times and scan downward at most 10 times. Randomize swipe endpoints and wait for inertia. Use ADB images for assets, excluding the roaming cat and courtyard background. Default scheduling remains disabled. Do not modify user profiles or commit.

**Review focus:** Corrupt/foreign history must trigger a full scan. Recent absence must retain history. OCR failure must not erase history. Truncated quantity rows must be skipped. Failed scans/navigation must not establish history or overwrite a valid baseline.

## Tasks

- [x] Add history validation/persistence and behavior tests for first/full and later/recent runs, identity isolation, zero quantities and partial failures.
- [x] Add inventory page transitions and stable ADB-captured entrance assets; reuse global login and costume presets.
- [x] Implement scan selection, safe merging, finite swipe/stability rules and courtyard return before saving.
- [x] Register task config, default template, menu and translations following existing OAS conventions.
- [x] Run focused tests and live full/recent workflows; inspect output and final courtyard screenshot.

## Implementation decisions

- History lives under config/asset_snapshot with a hashed identity filename, outside scheduler profiles.
- A missing/invalid baseline always uses Composite, including when force-full is enabled.
- Recent cannot determine items depleted to zero when they disappear from the group. A force-full setting supports refreshing such stale quantities.
- Public scan() remains a scan-only diagnostic entry; execute_workflow() performs navigation and persistence. run() handles scheduling and TaskEnd.

## Verification and limitations

- 24 focused unittest checks passed; 72-template asset validation and Python compilation passed.
- Live configured login from a stopped game completed via LoginService and returned to the courtyard after Recent scanning.
- Final Composite scan: 6 pages, 62 observed materials, 73 output variables. Final automatic Recent scan: 4 pages, 38 observed materials; all 30 unseen historical material fields retained their previous values.
- Results and per-category diagnostics are in log/asset_snapshot_workflow_{full,recent}_{result,scores}.json; final courtyard ADB screenshot is log/asset_snapshot_workflow_final_courtyard.png.
- Repeated reads keep the highest template score among valid quantity observations. Template score does not establish OCR accuracy: numeric omissions and similar-template errors remain a known limitation.
- Subagent review was cancelled at the user's explicit request; verification above was performed in the current session. No commits were created and user profiles were not edited.
