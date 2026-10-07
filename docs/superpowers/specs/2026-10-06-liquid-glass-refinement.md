# Liquid Glass refinement for the current workbench

Baseline: `b7a5ba507cd8192779debf56d32502ba38e8e6af`, verified against GitHub main on 2026-10-06. The current frontend already has three appearance preferences, bilingual bindings, local rounded fonts, glass tokens and segmented feedback. This work refines that implementation; it does not transplant the older UI experiment.

The user has authorized design decisions, implementation and validation without a separate design approval round. No merge or release is authorized.

## Decision

Three approaches were considered: material-only polish (small scope, leaves mobile usability issues), material and task-layout refinement (chosen), and a new navigation/layout architecture (unnecessary state and regression risk). Keep four routes and the existing configuration/session model.

The memorable element remains sqlseed's leaf/table mark and restrained green operation layer. Keep the bundled Sqlseed Rounded 400/500 for interface text and the existing monospace stack for identifiers/code. Base palette roles are canvas `#e5ebec`, reading surface `#fafcfb`, ink `#293b3e`, primary green `#24634f`, dark canvas `#172025`, and dark reading surface `#242e33`. State colors remain semantic and paired with text.

## Materials and layout

Use three roles: canvas, stable data surface, and glass controls/overlays. Data, code, rules, diffs and execution facts use a stable reading background; remove broad data-area backdrop blur. Navigation and temporary operation surfaces retain controlled blur, a subtle edge and short shadow. Controls keep consistent tokens; no ambient animation, pointer lighting or nested glass cards.

Desktop keeps the table directory beside the current table. On narrow screens, the directory becomes an explicit disclosure whose summary distinguishes the currently viewed table from the generated selection count. Keep its real DOM and independent checkbox/name/path actions. Selection/error navigation opens the directory before focusing a control; selecting a table brings its fields into view. Guide details collapse without removing the current next action or stage navigation. Global configuration controls remain directly reachable.

Table selection labels, dependency buttons and count steppers receive appropriate touch targets without making the whole table row a generation toggle. Main navigation stays discoverable in Chinese and English at 320px; do not turn routing buttons into tabs.

## Execution confirmation

Keep target identity, amount, plan details and explicit final consent. Add a short status near the footer actions and associate it with the submit button. It describes checking, writing, blocked, failed and ready states from the existing structured model and plan. Detailed diagnostics remain in the body; a user-activated detail link scrolls and focuses them. Responses never steal focus. The footer must not consume the entire short viewport.

All existing model identity, epoch/lifecycle, revision, plan hash, busy and canRun checks remain authoritative. The new display cannot grant execution permission or expand generation scope.

## Motion and accessibility

Keep existing segmented plates and immediate closing/focus restoration. Repair tab selection feedback so queued frames and every running decoration cancel on a new selection, reduced-motion preference changes or target removal. Vertical feedback decorates the selected surface, not the text. Selection/requests happen immediately; 140–180ms feedback may be interrupted.

Keep all three themes, language bindings, focus rings, Escape ownership, scroll locking and inert background. Extend existing reduced-transparency, unsupported-filter and forced-color fallback roles. Fine/coarse input layout remains independent of business state. XR is an architectural extension boundary, not a delivered client or claimed device acceptance.

## Sources

Official sources rechecked on 2026-10-06:

- [Materials](https://developer.apple.com/design/human-interface-guidelines/materials): control/navigation glass and regular versus clear materials.
- [Color](https://developer.apple.com/design/human-interface-guidelines/color): restrained tint and semantic emphasis.
- [Meet Liquid Glass](https://developer.apple.com/videos/play/wwdc2025/219/): optical continuity and avoiding glass-on-glass.
- [Motion](https://developer.apple.com/design/human-interface-guidelines/motion): precise, interruptible feedback adapted to input.
- [Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility): contrast and reduced motion/transparency.
- [visionOS hover interactions](https://developer.apple.com/videos/play/wwdc2025/303/): platform-owned gaze feedback, not simulated eye tracking.

CSS blur does not implement Apple's native optical system. Numeric CSS parameters are project choices, not Apple specifications.

## Acceptance contract

Preserve connections, the single executable document, independent viewing/generation/AI scopes, valid and invalid field drafts, read-only previews, reviewed AI application, explicit append/clear confirmation, run snapshots and plugin management capability checks. Verify through existing behavior suites plus meaningful new regressions and real browser workflows.

Exercise light/dark/system, Chinese/English, persistence and synchronization; 320/390/768/1024/1440px and actual browser 200% zoom; errors, busy/empty/unavailable states, long identifiers, dense graphs, keyboard/focus/Escape, interrupted feedback, and transparency/motion fallbacks. Compare before/after screenshots, content reachability and representative load/scroll/interaction performance. Only disposable isolated SQLite fixtures may be written. Model boundary substitutes must be labeled; no live model or user-environment package mutation.

Delivery includes source commits, a reviewable PR, working candidate preview, feature/test evidence and explicit limitations. A screenshot or Node DOM test alone is insufficient to claim browser or full business acceptance.
