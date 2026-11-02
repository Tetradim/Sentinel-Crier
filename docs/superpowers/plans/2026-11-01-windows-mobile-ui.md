# Windows mobile-style workspace implementation plan

> Agentic workers: use subagent-driven-development for separate theme and ticket work, followed by independent review.

**Goal:** Make the native Windows interface closely match Crier mobile's account-first dark brokerage UI.

**Design:** Retain Tk and the existing execution/session interfaces. A shared dark palette, compact account/environment header, persistent Stop control, mobile-style Home/Markets/Trade/Positions/Orders navigation and an Account hub replace the exposed setup-tab strip. Existing setup, delivery, pricing, provider, copy dashboard, health and update pages remain accessible through Account. Markets explicitly reports the absent feed; Home shows retained activity counts and unavailable balances rather than invented values. Trading forms and tables retain their current action guards, original IDs and routes.

**Alternatives:** A color-only reskin would retain the crowded navigation. Rebuilding Windows around a web view would introduce new packaging/runtime and broker seams. The existing native shell with mobile navigation provides close parity while preserving the tested execution model.

**Tech stack:** Python/Tk/ttk, existing Windows build and installer workflows. Colors and hierarchy follow the already approved native mobile screens.

- [x] Add meaningful failing tests for navigation, unavailable data, global stop, route changes and disabled trading.
- [x] Extract and apply a shared dark theme to native widgets, tables and dialogs.
- [x] Restyle the ticket with stock/option controls and clear buy/management actions; preserve frozen command semantics.
- [x] Implement mobile-style shell, account hub and real-state Home. Keep existing notebook page references usable by internal navigation/tests.
- [x] Run targeted and full Python/Tk tests, independently review the changes and inspect actual isolated desktop screenshots at scaled window sizes.
- [x] Publish a Windows update from verified source and record source-specific acceptance and screenshots. Mobile builds and deferred provider/device work remain outside this visual Windows change.
