# Monetic AI Reconciliation

[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-15-000000?logo=nextdotjs&logoColor=white)](https://nextjs.org/)
[![SQLite](https://img.shields.io/badge/SQLite-audit_trail-003B57?logo=sqlite&logoColor=white)](https://sqlite.org/)

A Level-4 issuer/acquirer clearing reconciliation demo built with deterministic Python business logic and optional Agno/Gemini agent orchestration.

The project compares clearing batches from issuer and acquirer sides, detects matched transactions, mismatches, duplicates, issuer-only items, and acquirer-only items, then produces operator-friendly summaries for payment operations teams.

## Why This Exists

In card payment operations, issuer and acquirer clearing files need to agree on key transaction data such as RRN, PAN, amount, currency, and date. When they do not match, teams need to investigate differences quickly before settlement, dispute, or accounting issues grow.

This project models a small reconciliation assistant that can:

- Parse issuer and acquirer clearing batches.
- Normalize dates and amounts.
- Match transactions by RRN.
- Detect amount, currency, and date mismatches.
- Flag issuer-only and acquirer-only records.
- Produce structured metrics and human-readable summaries.
- Optionally use an agent layer for orchestration and reporting.

## Features

- Deterministic reconciliation core that works without an LLM.
- Optional Agno/Gemini layer for planner and reporter flows.
- JSON, XML, CSV, and ZIP input support.
- Date tolerance and amount tolerance configuration.
- Pydantic validation for input records.
- SQLite audit trail support.
- FastAPI service and Next.js UI for upload-based workflows.
- Synthetic test-data generation through `make_test_data.py`.

## Stack

| Layer | Technology |
| --- | --- |
| Backend | Python, FastAPI, Pydantic, SQLAlchemy |
| Reconciliation | Deterministic matching and mismatch detection |
| Agent layer | Agno with optional Gemini model integration |
| UI | Next.js 15, React 19, TypeScript, Tailwind |
| Storage | SQLite audit database |
| Inputs | JSON, XML, CSV, ZIP |

## Repository Layout

```text
.
├── config/                    # reconciliation defaults and policy config
├── overrides/                 # optional override examples
├── tests/                     # synthetic input scenarios
├── ui/                        # Next.js UI
├── l4_clearing_recon.py       # deterministic reconciliation engine
├── make_test_data.py          # ZIP fixture generator
├── playground.py              # FastAPI / agent playground entrypoint
├── ui_recon_api_only.py       # UI API adapter
├── ui_recon_tools.py          # upload and UI tools
├── requirements.txt
└── readme.md
```

## Requirements

- Python 3.9+
- Node.js 18+ for the UI
- Optional: Google Gemini API key for agent-assisted summaries

## Quick Start

### 1. Clone and install backend dependencies

```bash
git clone https://github.com/YahyaSaadaoui/monetic-ai-reconciliation.git
cd monetic-ai-reconciliation

python -m venv agnoenv

# Windows
agnoenv\Scripts\activate

# macOS/Linux
source agnoenv/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment

Create `.env` from `.env.example`:

```bash
cp .env.example .env
```

Example values:

```env
GOOGLE_API_KEY=
WEBHOOK_URL=
DB_PATH=./reversal_audit.db
MODEL_ID=gemini-1.5-flash
DATE_TOL_DAYS=2
```

The deterministic reconciliation logic does not require `GOOGLE_API_KEY`. It is only needed for optional Gemini-powered agent behavior.

### 3. Run CLI examples

```bash
python l4_clearing_recon.py tests/pair_ok/json/issuer_clearing.json tests/pair_ok/json/acquirer_clearing.json
```

Generate zipped test fixtures:

```bash
python make_test_data.py
```

### 4. Run the service/UI

Start the backend:

```bash
python playground.py
```

Start the UI:

```bash
cd ui
pnpm install
pnpm dev -p 3000
```

Or with npm:

```bash
cd ui
npm install
npm run dev -- -p 3000
```

## Input Model

Each clearing transaction contains:

| Field | Meaning |
| --- | --- |
| `rrn` | Retrieval reference number used for matching |
| `pan` | Masked PAN, for example `****1111` |
| `amount` | Transaction amount |
| `currency` | Currency code |
| `date` | Clearing date |

Each batch is marked or inferred as `issuer` or `acquirer`.

## Reconciliation Output

The engine produces:

- `matched`: transactions that agree within configured tolerances.
- `mismatches`: transactions with amount, currency, or date differences.
- `issuer_only`: records missing from acquirer side.
- `acquirer_only`: records missing from issuer side.
- `metrics`: count summaries for operators.
- `summary_md`: readable operational summary.

## Good First Improvements

- Add more test scenarios under `tests/`.
- Add a README screenshot or GIF of the UI upload flow.
- Add Docker Compose for backend + UI startup.
- Add unit tests for duplicate RRN handling and tolerance logic.
- Add examples for multi-currency settlement edge cases.
- Rename the audit database variables from reversal wording to reconciliation wording.

## Security Notes

This is a demo project. Do not commit real card data, internal clearing files, production configs, private keys, tokens, or real customer information. Use masked PANs and synthetic transactions only.

## License

Add a license before using this in shared or commercial contexts.
