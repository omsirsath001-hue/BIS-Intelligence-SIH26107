# BIS Intelligence — NVIDIA Nemotron + Comprehensive BIS Knowledge

This build is designed as a BIS research/compliance assistant, not as a static dump of every Indian Standard.

## What is included

- NVIDIA NIM final answer generation with `nvidia/nemotron-3-super-120b-a12b`.
- English, Hindi and Marathi voice search.
- Local evidence retrieval with SQLite + TF-IDF.
- A broad official BIS knowledge registry covering:
  - BIS Act, Rules and Regulations
  - Indian Standards and Know Your Standard
  - voluntary vs compulsory certification
  - Quality Control Orders (QCOs)
  - Scheme I / ISI Mark product certification
  - Scheme II / CRS
  - Scheme IV / Certificate of Conformity
  - Scheme X
  - Foreign Manufacturers Certification Scheme (FMCS)
  - product certification application, inspection, testing, surveillance, renewal and cancellation
  - laboratories and product manuals
  - hallmarking meaning, gold/silver, HUID, jeweller registration, A&H centres, refineries, consumer testing and mandatory hallmarking
  - consumer protection, complaints and product recalls
  - standardization and emerging areas
  - management systems and Eco Mark
  - official forms and application resources
- Official-source registry at `data/bis_official/source_registry.json`.
- Optional official BIS crawler at `scripts/sync_bis.py`.

## Important accuracy design

No software package can truthfully contain "every BIS standard forever" because BIS publishes new standards, revisions, amendments, corrigenda, withdrawals and QCO changes. The app therefore uses two layers:

1. A packaged official BIS domain knowledge base for broad questions.
2. A conservative refresh script that starts only from official BIS URLs and indexes public BIS pages/PDFs into the local database.

For a specific IS number, QCO, amendment, licence status, fee, effective date or current legal requirement, the assistant should link/verify the current official BIS source and should not invent missing facts.

The official BIS Know Your Standard portal is the authoritative discovery point for a selected standard and can expose the standard, amendments, gazette notifications, schemes of testing/inspection, licences and laboratories.

## NVIDIA configuration

Create `backend/.env`:

```env
NVIDIA_API_KEY=YOUR_NVIDIA_SECRET_KEY
NVIDIA_MODEL=nvidia/nemotron-3-super-120b-a12b
NVIDIA_API_URL=https://integrate.api.nvidia.com/v1/chat/completions
NVIDIA_TIMEOUT=90
```

## Run backend

```powershell
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000
```

## Run frontend

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`.

## Refresh BIS public knowledge

Start the backend once so the database exists, then from the project root run:

```powershell
python scripts/sync_bis.py --max-pages 500 --max-pdfs 100 --delay 0.5
```

To also download/index public BIS PDFs discovered from official BIS pages:

```powershell
python scripts/sync_bis.py --max-pages 1000 --max-pdfs 200 --download-pdfs --delay 0.75
```

Use a reasonable delay and do not run aggressive crawling. The script only follows `bis.gov.in` links.

## API checks

- `GET http://127.0.0.1:8000/health`
- `GET http://127.0.0.1:8000/api/nvidia/status`
- `GET http://127.0.0.1:8000/api/bis/catalog`
- `GET http://127.0.0.1:8000/api/bis/knowledge-status`
