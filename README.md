# DecMD — Flask + PostgreSQL demo edition

This repository hosts the Flask application, **not** GitHub Pages. All clinical records are synthetic. This is a hackathon demonstration, not production clinical software.

## Local setup (Python 3.11+)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env: set secure SECRET_KEY, PostgreSQL DATABASE_URL, ALLOW_DEMO_SEED=1, and DEMO_PASSWORD
set -a; source .env; set +a
flask --app wsgi init-db
flask --app wsgi seed-demo
flask --app wsgi run
```

Visit http://127.0.0.1:5000/login.

**Seeded accounts:** doctor@decmd.demo (Dr. Rafael Reyes), patient@decmd.demo (Maya Santos). Both use **the password you set in DEMO_PASSWORD**. No hardcoded passwords are shipped in source. The clinician account is approved only as part of explicitly enabled seed-demo command. Public doctor signups await approval and cannot elevate themselves.

## Hosted deployment (Render, Railway, or other Python host)

1. Create a PostgreSQL database and a Python web service pointing to this repository.
2. Set environment variables **in hosting provider dashboard**: `APP_ENV=production`, `SECRET_KEY` (random 32+ bytes), `DATABASE_URL` (managed postgres connection), `ALLOW_DEMO_SEED=1` temporarily for synthetic demo, `DEMO_PASSWORD` (unique 12+ character random password). Never commit `.env`.
3. Build command: `pip install -r requirements.txt`
4. Pre-deploy/one-time initialization: `flask --app wsgi init-db && flask --app wsgi seed-demo`
5. Start command: `gunicorn wsgi:app --bind 0.0.0.0:$PORT`
6. Disable seed after running: `ALLOW_DEMO_SEED=0`.
7. Share the Python-hosted web service URL, **not a github.io URL**. GitHub Pages does not run Python.

**Security boundary:** The original static showcase interactions were retained, but the dataset is loaded only into authenticated responses and backed by a PostgreSQL records table. All records are synthetic; peer retrieval, cryptographic source verification, and final clinical review **are illustrative** and not connected to hospitals. New signup patients start with no real/seeded records. Do not store personal health information or use this demo for care decisions.

## Verification

Run `node --check docs/app.js` and `python -m compileall -q app.py wsgi.py`. Run server and manually test doctor login, patient login, signup, graph expansion, source pages, and record audit. PostgreSQL connection and browser interaction tests were not executable in packaging runtime.
