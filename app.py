"""DecMD synthetic clinical demonstration. Not an EHR or live source federation."""
import json
import os
import secrets
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

ROOT = Path(__file__).parent
app = Flask(__name__, template_folder='templates')
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY') or ('local-development-only-key' if os.getenv('APP_ENV') != 'production' else None)
if not app.config['SECRET_KEY']:
    raise RuntimeError('SECRET_KEY must be set in production')
raw = os.getenv('DATABASE_URL', 'sqlite:///' + str(ROOT / 'decmd_local.db'))
if raw.startswith('postgres://'):
    raw = 'postgresql+psycopg://' + raw[len('postgres://'):]
elif raw.startswith('postgresql://'):
    raw = 'postgresql+psycopg://' + raw[len('postgresql://'):]
if os.getenv('APP_ENV') == 'production' and raw.startswith('sqlite:'):
    raise RuntimeError('PostgreSQL DATABASE_URL is required for production')
app.config.update(SQLALCHEMY_DATABASE_URI=raw, SQLALCHEMY_TRACK_MODIFICATIONS=False,
                  SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                  SESSION_COOKIE_SECURE=os.getenv('APP_ENV') == 'production', MAX_CONTENT_LENGTH=1_000_000)
db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(160), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='patient')
    approved = db.Column(db.Boolean, nullable=False, default=False)
    patient_id = db.Column(db.String(32))

class ClinicalRecord(db.Model):
    id = db.Column(db.String(80), primary_key=True)
    patient_id = db.Column(db.String(32), nullable=False, index=True)
    payload = db.Column(db.JSON, nullable=False)

class AuditEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    event = db.Column(db.String(100), nullable=False)
    detail = db.Column(db.String(350), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

FIXTURES = json.loads((ROOT / 'seed_records.json').read_text())

def csrf_token():
    if '_csrf' not in session:
        session['_csrf'] = secrets.token_urlsafe(32)
    return session['_csrf']
app.jinja_env.globals['csrf_token'] = csrf_token

@app.before_request
def validate_post():
    if request.method == 'POST':
        got = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
        if not got or not secrets.compare_digest(got, session.get('_csrf', '')):
            abort(400, description='Session token missing or expired; reload and try again')

def current_user():
    uid = session.get('user_id')
    return db.session.get(User, uid) if uid else None

def login_required(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for('login'))
        return func(*args, **kwargs)
    return wrapped

def record_event(user, event, detail=''):
    db.session.add(AuditEntry(user_id=user.id, event=event[:100], detail=str(detail)[:350]))
    db.session.commit()

@app.route('/brand/decmd-mark.png')
def brand_mark():
    # Public logo asset used on the login and signup pages.
    return send_from_directory(ROOT / 'docs' / 'assets', 'decmd-mark.png')

@app.route('/healthz')
def healthz():
    return jsonify(status='ok')

@app.route('/docs/<path:filename>')
@login_required
def static_docs(filename):
    return send_from_directory(ROOT / 'docs', filename)

@app.route('/')
@login_required
def home():
    user = current_user()
    query = ClinicalRecord.query
    if user.role == 'patient':
        query = query.filter_by(patient_id=user.patient_id)
    elif user.role != 'doctor' or not user.approved:
        abort(403)
    records = [item.payload for item in query.order_by(ClinicalRecord.id).all()]
    people = [FIXTURES['patient']] if user.role == 'doctor' or user.patient_id == 'p0' else [{'id':user.patient_id, 'name':user.display_name, 'family':'Personal'}]
    data = {'hospitals': FIXTURES['hospitals'], 'people': people, 'records': records}
    page = (ROOT / 'index.html').read_text()
    # JSON-safe embedding; never insert HTML from user-controlled fields.
    safe = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    return page.replace('__SERVER_BOOTSTRAP__', safe).replace('__SERVER_CSRF__', csrf_token())

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET' and current_user():
        return redirect(url_for('home'))
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password_hash, password):
            flash('Incorrect email or password.')
        elif not user.approved:
            flash('This clinician account is awaiting approval.')
        else:
            session.clear()
            session['user_id'] = user.id
            csrf_token()
            record_event(user, 'login', 'Signed in')
            return redirect(url_for('home'))
    return render_template('auth.html', mode='login')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'GET' and current_user():
        return redirect(url_for('home'))
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        name = (request.form.get('name') or '').strip()
        role = request.form.get('role', 'patient')
        if role not in ('patient', 'doctor') or len(name) < 2 or len(name) > 160 or len(email) > 200 or '@' not in email or len(password) < 12:
            flash('Use a valid name, email, and password of at least 12 characters.')
        elif User.query.filter_by(email=email).first():
            flash('Account already exists. Please sign in.')
        else:
            # New synthetic patient accounts are limited to their own empty record space.
            # Doctor accounts need manual approval; no public privilege escalation.
            user = User(email=email, password_hash=generate_password_hash(password), display_name=name,
                        role=role, approved=(role == 'patient'), patient_id=(secrets.token_hex(8) if role == 'patient' else None))
            db.session.add(user)
            db.session.commit()
            if user.approved:
                session.clear()
                session['user_id'] = user.id
                csrf_token()
                record_event(user, 'signup', 'Created synthetic patient account')
                flash('Account created. You are signed in as a patient.')
                return redirect(url_for('home'))
            flash('Clinician account created. Approval is required before you can sign in. For immediate access, register as Patient.')
            return redirect(url_for('login'))
    return render_template('auth.html', mode='signup')

@app.route('/logout')
def logout():
    user = current_user()
    if user:
        record_event(user, 'logout', 'Signed out')
    session.clear()
    return redirect(url_for('login'))

@app.route('/api/me')
@login_required
def me():
    user = current_user()
    return jsonify(name=user.display_name, role=user.role, approved=user.approved)

@app.route('/api/records')
@login_required
def api_records():
    user = current_user()
    if user.role == 'doctor' and user.approved:
        q = ClinicalRecord.query
    else:
        q = ClinicalRecord.query.filter_by(patient_id=user.patient_id)
    return jsonify([r.payload for r in q.all()])

@app.route('/api/audit', methods=['GET', 'POST'])
@login_required
def api_audit():
    user = current_user()
    if request.method == 'POST':
        info = request.get_json(silent=True) or {}
        record_event(user, str(info.get('event', 'interaction')), info.get('detail', ''))
        return jsonify(ok=True), 201
    items = AuditEntry.query.filter_by(user_id=user.id).order_by(AuditEntry.id.desc()).limit(100).all()
    return jsonify([{'event': x.event, 'detail': x.detail, 'date': x.created_at.isoformat()} for x in items])

@app.cli.command('init-db')
def init_db():
    db.create_all()
    print('Database schema initialized')

@app.cli.command('seed-demo')
def seed_demo():
    if os.getenv('ALLOW_DEMO_SEED') != '1':
        raise RuntimeError('Set ALLOW_DEMO_SEED=1 to allow synthetic demo account seeding')
    db.create_all()
    password = os.getenv('DEMO_PASSWORD')
    if not password or len(password) < 12:
        raise RuntimeError('Set a DEMO_PASSWORD with at least 12 characters')
    identities = [('doctor@decmd.demo','Dr. Rafael Reyes','doctor',None), ('patient@decmd.demo','Maya Santos','patient','p0')]
    for email, name, role, pid in identities:
        user = User.query.filter_by(email=email).first()
        if not user:
            db.session.add(User(email=email, display_name=name, role=role, patient_id=pid,
                                approved=True, password_hash=generate_password_hash(password)))
    for entry in FIXTURES['records']:
        if not db.session.get(ClinicalRecord, entry['id']):
            db.session.add(ClinicalRecord(id=entry['id'], patient_id=entry['patient'], payload=entry))
    db.session.commit()
    print(f'Seeded: doctor@decmd.demo and patient@decmd.demo; {len(FIXTURES["records"])} synthetic patient records')

if __name__ == '__main__':
    app.run(debug=os.getenv('APP_ENV') != 'production')
