# Ad Ingestion MVP

**Peak Ventures · Media Buying Ops**

Scrape competitor FB ads → cluster into topics → select angles → generate copy variants → review & approve → launch brief + Google Sheet log.

## Setup

### 1. Python environment
```bash
cd pv-media_buying/ad-ingestion-mvp
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Install Playwright browser
```bash
playwright install chromium
```

### 3. Environment variables
```bash
cp .env.example .env
# Edit .env and add your Anthropic API key
```

### 4. Google Sheets (optional — needed for Sheet logging)
- Copy your `credentials.json` (Google service account) into this directory
- Create a new Google Sheet and share it with the service account email
- Set the `spreadsheet_id` in `config.yaml`

## Run
```bash
streamlit run app.py
```

Opens at http://localhost:8501

## Workflow
1. **Input** — Paste FB Ad Library URL (or upload CSV), enter your PV domain + initials
2. **Gate 1** — Review ranked topics, select angles to generate for
3. **Gate 2** — Edit/approve/reject copy variants
4. **Output** — Copy launch brief, log to Google Sheet
