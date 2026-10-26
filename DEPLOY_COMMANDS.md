# Copy/paste for hosted Python service

Build: `pip install -r requirements.txt`

Start: `gunicorn wsgi:app --bind 0.0.0.0:$PORT`

One-time initialize after setting secrets and DATABASE_URL:

```bash
flask --app wsgi init-db
flask --app wsgi seed-demo
```

Run those commands from a provider shell or a one-time release command; if no shell access, configure a one-off deploy job.

Never enable GitHub Pages for this app and never publish your PostgreSQL password.
