# The San Francisco Bulletin

A neighborhood newspaper generated from San Francisco public records.

The application ingests high-signal DataSF datasets, assigns every record to an official Analysis Neighborhood, compares the latest seven-day period with the preceding four-week baseline, and turns the results into readable neighborhood editions rather than a conventional dashboard.

## Initial data desk

- Registered Business Locations — `g8m3-pdis`
- Building Permits — `i98e-djp9`
- 311 Cases — `vw6y-z8j6`
- Police Incident Reports — `wg3w-h783`

The source registry in `bulletin/config.py` is designed to support additional DataSF feeds without changing the newspaper templates.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload
```

Open `http://127.0.0.1:8000`.

The first snapshot is built in the background. `GET /api/health` reports whether a snapshot is available and any DataSF refresh error.

## DataSF app token

A Socrata app token is optional but recommended for higher request limits. Set:

```bash
export DATASF_APP_TOKEN=your_token
```

The app does not require a DataSF username or password.

## Render deployment

This repository includes `render.yaml` and a Dockerfile. Create a Render Blueprint from this repository. The Blueprint provisions:

- one Docker web service
- `/api/health` health checks
- a 1 GB persistent disk at `/var/data`
- six-hour DataSF refreshes
- an optional secret `DATASF_APP_TOKEN`

The persistent snapshot means the last successful edition stays online even if DataSF is temporarily unavailable.

## API

- `GET /` — city front page
- `GET /neighborhood/{slug}` — neighborhood newspaper edition
- `GET /api/bulletin` — complete generated snapshot
- `GET /api/health` — service/cache health
- `GET /api/refresh` — manual refresh

## Methodology

Each source is anchored to its own latest available date so a lagging dataset does not create a false decline. The primary comparison is:

- **Current:** trailing seven days
- **Baseline:** average weekly count during the preceding 28 days
- **Trend context:** eight trailing seven-day windows

The significance score is a deterministic prioritization signal based on deviation from baseline, volume, and percentage change. It is used to choose headlines, not to assign value judgments.

Police incident records are described as *reported incidents* and are not presented as a direct measure of neighborhood safety.
