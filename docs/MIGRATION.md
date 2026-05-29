# Migration map — shoelessjoes-supplier-py

Transitional Python pipeline for DealernetX pricing intelligence. Long-term logic migrates into `shoelessjoes-ops`; keep this repo runnable until that cutover.

## Source (legacy)

| Path | What to port |
|------|----------------|
| `C:\Users\burke\Git\shoeless-joes\` | Python supplier price checker |

Key folders/files:

- `src/` — CLI (`main.py`), Playwright scraper, Shopify client, matcher, alerts, review pack
- `configs/` — `dealernetx.daily.yaml`, `.oos.yaml`, `.weekly.yaml`, base `dealernetx.yaml`
- `scripts/` — `register-scheduled-tasks.ps1`, scheduled `.cmd` jobs, `cleanup-out.ps1`
- `requirements.txt`
- `.env.example`
- `docs/PROJECT_STATE.md` — last known validation notes
- `integrations/dealernet/` — intake sheet headers (optional)
- `integrations/google_apps_script/` — vendor invoice logger (optional)

## GitHub

- **Target:** `github.com/shoelessjoes/shoelessjoes-supplier-py`
- **Archive (do not delete):** old `shoeless-joes` / `supplier-price-dashboard` repos

## Local clone path

`C:\Users\burke\Git2\shoelessjoes-supplier-py\`

## Related docs

- Storefront handoff: `../shoelessjoes-storefront/docs/HANDOFF.md`
- Node ops target: `../shoelessjoes-ops/docs/MIGRATION.md`
- Stack overview: `DEALERNET_STACK.md`
- Zip archive `C:\Users\burke\Git\dealernet-shopify-ops.zip` matches live `dealernet-shopify-ops` @ `5f95a8d` (no extra files vs clone)

## Status

- [x] Copy `src/`, `configs/`, `scripts/`, `requirements.txt`, `.env.example`
- [x] Copy README content from legacy (full CLI docs)
- [ ] Verify `python -m src.main test-login` against DealernetX
- [ ] Re-register Windows scheduled tasks pointing at this path
