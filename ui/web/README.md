# Castellan — Mission Control UI

The read-only browser interface for Castellan's audit chain and case lifecycle.

## Views

| Route | What it shows |
|---|---|
| `/` | Dashboard — one case, end to end, with a live proof card |
| `/chain` | SHA-256 audit chain — VALID verdict, sealed records, tamper test |
| `/lifecycle` | Numbered 1–7 record sequence, each expandable to raw sealed JSON |
| `/reversibility` | Before/after rollback round-trip, byte-for-byte verified |

## Architecture

The frontend never holds Band credentials. A thin **FastAPI read-bridge** (`ui/api/`) proxies all data through the same proven `connection/audit_reader.py` functions used by the CLI auditor — so what you see in the browser is exactly what `audit_verify.py` computes.

## Running

From the **repo root**:

```bash
# Start the read-bridge first (port 8000)
uv run uvicorn ui.api.main:app --reload --port 8000

# Then start the frontend (port 3000)
cd ui/web
npm install
npm run dev
```

Open `http://localhost:3000`.

## Stack

Next.js 16 (App Router) · TypeScript · Tailwind CSS v4 · Turbopack

## Note on Turbopack cache

If styles fail to load after editing files while the dev server is running, clear the cache and hard-refresh:

```bash
Remove-Item -Recurse -Force .next   # PowerShell (Windows)
# or
rm -rf .next                         # bash/zsh
npm run dev
```
