# Frontier Results and Same-Run Divergent Phase

## Goal

Restore Frontier as a complete review/result phase and make Divergent a manual continuation inside the same research run.

## Scope

- Frontier must continue from deep reading into comparison, pain mining, and summary generation.
- Frontier outputs must persist rich review data, including summaries, paper reviews, gaps, method landscape, entry points, and pain-point package.
- The Frontier results page must render these review fields and keep discovered papers collapsed by default with library actions.
- Divergent must be triggered manually from Frontier results with `start_divergent`, reuse the same run id, and receive the flattened Frontier context bundle expected by the worker.
- Automatic child Divergent spawning should be opt-in only.
- The run console should expose same-run Divergent status/results after the manual phase starts.

## Verification

- Targeted Python tests cover Frontier graph completion, context bundle persistence, API action behavior, and auto-spawn policy.
- Static UI tests cover Frontier review rendering and same-run Divergent links.
- `npm --prefix apps/web run build` verifies frontend type and production build integrity.
