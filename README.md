# StreamVault Licensing Analysis

This project analyzes a supplied TMDb movie-ID list for audience evidence,
franchise and standalone negotiation candidates, and talent patterns. Audience
ratings are not license prices, rights availability, or financial returns.

## Set up on Windows

Use Python 3.14, the version used by continuous integration. From the
repository root in PowerShell:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Create a private `.env` file in the repository root and add your key:

```text
TMDB_API_KEY=your_tmdb_api_key
```

Keep `.env` private and out of version control.
Optional request controls can be added to the same `.env` file or set as
process environment variables. They default to three attempts, one second of
exponential retry backoff, and 0.25 seconds between movie IDs:

```text
TMDB_MAX_ATTEMPTS=3
TMDB_BACKOFF_SECONDS=1.0
TMDB_REQUEST_DELAY_SECONDS=0.25
```

## Run the full workflow

From the repository root, with the virtual environment active:

```powershell
python -m src.pipeline
```

The pipeline refreshes movie and credits data, writes the row-level acquisition
log, generates both time-window analyses and negotiation shortlists, then
evaluates any complete offers in `data/raw/license_offers_template.csv`.
Acquisition failures remain visible in the reconciliation output; cached
records are retained when a refresh fails.
If the run has no valid movie records and no usable cached copies, it stops
after saving the acquisition log and leaves the prior movie file unchanged.

On the first run, the pipeline initializes candidate rows in the offer
template if it is missing or all offer-term fields are blank. It preserves
entered offer terms; no fee or rights information is invented.

The offer template is intentionally blank until verified fees, rights,
territory, dates, and quote sources are entered. Without complete offers, the
licensing report correctly returns `no_eligible_offers`. Never infer a bid
from TMDb ratings or popularity.

## Run the notebook and tests

Run the full pipeline once before opening
`notebooks/streamvault_analysis.ipynb`; the notebook uses saved project data
and does not make API calls.

```powershell
python -m pytest -q
```

GitHub Actions runs this test suite with Python 3.14 on pushes and pull requests
to `main`.

Generated CSV reports and the client memo are written to `reports/`. Key
outputs include the ranked franchise and standalone lists, talent signals,
data diagnosis, candidate reconciliation, decision notes, and licensing
scenario. Accepted architecture decisions are documented one per file in
`decisions/`.
