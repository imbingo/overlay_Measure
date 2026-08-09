# SOMA Vision Metrology V2.2.0

V2.2.0 focuses on measurement correctness and production safety.

## Main changes

- Physical-coordinate circle fitting for non-square pixels and corrected minimum-enclosing-circle diameter.
- ROI-level failure isolation and complete Excel failure traceability.
- Background Auto Identify / Analyze ROI with progress and cancellation.
- Lazy batch image loading to reduce memory usage.
- Production-mode canvas/backend ROI lock and centralized stale-result invalidation.
- Explicit ROI parameter Apply, context-aware controls, and 20-step ROI undo/redo.
- Recovery job lifecycle records and clearer run/export guidance.

Existing V2.1 recipes remain compatible. Overlay formulas and recipe ROI data structures are unchanged.
