# JNPA Project & Expense Management

Flask application based on the supplied `app.py`, reorganized into separate configuration, database, and model modules. It supports local SQLite and production PostgreSQL.

## Local Windows setup

```powershell
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
$env:SECRET_KEY="replace-with-a-long-random-value"
python app.py
```

Open http://127.0.0.1:8080/ . The database file `expense_manager.db` is created automatically.

Create an administrator on a fresh database:

```powershell
$env:ADMIN_USERNAME="admin"
$env:ADMIN_PASSWORD="Use-a-strong-password-here"
flask --app app create-admin
```

Create an employee and manager user accounts through an administrator provisioning workflow before using those roles. Do not use demo/default passwords in production.

## OpenShift deployment with Python S2I

### 1. Prepare source in Git

Commit the complete project folder to your Git repository. Ensure `requirements.txt`, `app.py`, `wsgi.py`, `config.py`, `database.py`, `models.py`, `templates/`, and `static/` are at the repository root.

### 2. Create a PostgreSQL database

Use your organization's approved PostgreSQL service/operator or managed PostgreSQL instance. Create a database and credentials. Do not use SQLite for production because container filesystems may be ephemeral and replicas do not share a local SQLite file.

### 3. Create an OpenShift project

```bash
oc new-project jnpa-expense
```

### 4. Create application from source using S2I

The Python builder image tag available in your cluster may differ. Check available tags in your OpenShift registry/catalog. Example:

```bash
oc new-app python:3.11-ubi9~https://github.com/akshaypawar056/jnpa.git \
  --name=jnpa-expense \
  --strategy=source
```

If your cluster does not provide `python:3.11-ubi9`, select an available supported Python 3.11 S2I builder image and substitute its image stream/tag.

### 5. Configure environment variables

Set these values using your real PostgreSQL service details:

```bash
oc create secret generic jnpa-app-secret \
  --from-literal=SECRET_KEY='replace-with-a-long-random-secret' \
  --from-literal=DATABASE_URL='postgresql+psycopg://DB_USER:DB_PASSWORD@DB_HOST:5432/DB_NAME'
oc set env deployment/jnpa-expense --from=secret/jnpa-app-secret
```

Protect the secret and restrict who can read it. Prefer TLS/SSL settings required by your database provider.

### 6. Expose the service using an OpenShift Route

```bash
oc expose service/jnpa-expense
oc get route jnpa-expense
```

Open the `https://...` or `http://...` host shown by the route command. For HTTPS termination, configure a TLS edge route according to your cluster policy.

### 7. Verify deployment

```bash
oc get pods
oc logs deployment/jnpa-expense
oc get svc
oc get route
```

The application includes `/healthz` for a basic health check.

## OpenShift persistence notes

- PostgreSQL is the recommended persistent database.
- Uploaded receipts currently go to `UPLOAD_FOLDER` (default `/tmp/jnpa-uploads`). `/tmp` is not durable. For production, mount a persistent volume claim and set `UPLOAD_FOLDER` to its mount path, or move receipt storage to an approved object-storage service.
- Do not scale multiple replicas with local SQLite or container-local uploads.
- Set resource requests/limits and readiness/liveness probes according to your cluster standards.
- Database schema creation uses `db.create_all()` for initial setup. For future schema changes, introduce Flask-Migrate/Alembic migrations rather than relying on `create_all()`.

## Security and production checklist

- Set a unique, long `SECRET_KEY`.
- Use a strong administrator password and create accounts through a controlled provisioning process.
- Add CSRF protection (for example Flask-WTF) before exposing forms to untrusted networks.
- Configure HTTPS route, database TLS, backups, and restricted database/network access.
- Review role permissions and audit requirements with your organization before production use.
- The included app intentionally does not create default admin/manager/employee credentials.
