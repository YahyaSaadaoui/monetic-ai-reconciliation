# Contributing

Thanks for considering a contribution to `monetic-ai-reconciliation`.

This project is a payment-operations demo for issuer/acquirer clearing reconciliation. Contributions should keep the reconciliation logic deterministic, testable, and understandable for people learning fintech operations automation.

## Useful Contribution Areas

- Add more synthetic issuer/acquirer clearing scenarios under `tests/`.
- Add unit tests for RRN matching, duplicates, amount tolerance, and date tolerance.
- Improve malformed JSON, XML, CSV, and ZIP validation errors.
- Add Docker Compose for backend and UI startup.
- Add UI screenshots or a short demo GIF to the README.
- Improve operator summaries for mismatch and exception cases.
- Add examples for multi-currency clearing or duplicate RRN handling.

## Local Setup

```bash
python -m venv agnoenv

# Windows
agnoenv\Scripts\activate

# macOS/Linux
source agnoenv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

Run a CLI example:

```bash
python l4_clearing_recon.py tests/pair_ok/json/issuer_clearing.json tests/pair_ok/json/acquirer_clearing.json
```

Generate ZIP fixtures:

```bash
python make_test_data.py
```

Run the UI:

```bash
cd ui
pnpm install
pnpm dev -p 3000
```

## Before Opening a PR

Please check the following:

- The deterministic CLI flow still works.
- New fixtures use masked PANs and fake transaction data.
- Any new behavior is documented in the README or code comments where useful.
- No real card data, internal clearing files, credentials, or production configs are committed.

## PR Format

```markdown
## Summary
Explain what changed and why.

## Testing
- Ran `python l4_clearing_recon.py ...`
- Added/updated synthetic fixtures if applicable

## Notes
Mention limitations or follow-up work.
```

## Security

Never commit real PANs, real customer data, live payment files, production logs, private URLs, API keys, or database dumps. Use synthetic transaction data only.
