# JNPA Project & Expense Management — Three-tier starter

## Architecture

1. **Presentation tier:** `templates/` and `static/` — browser UI (HTML/CSS).
2. **Application tier:** `app.py` and `wsgi.py` — Flask routes, business logic, approvals and Excel export.
3. **Data tier:** `models.py` and `database.py` — SQLAlchemy models and database connection.

For OpenShift, run Flask as an S2I application workload and PostgreSQL as a separate persistent database service. In this starter, presentation and application source layers are packaged in one Flask web workload; PostgreSQL is a separate data tier.

## Push to GitHub

1. Create an empty GitHub repository.
2. Extract this ZIP and upload the *contents* of `jnpa-expense-management/` to the repository root.
3. Check that `requirements.txt`, `app.py`, `wsgi.py`, `.s2i/`, `templates/`, and `static/` are visible at the root.
4. Commit to the `main` branch.

## Local Windows run

```powershell
py -3.11 -m venv .venv
.venv\\Scripts\\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
$env:SECRET_KEY="replace-with-a-long-random-value"
python app.py
```

Open `http://127.0.0.1:8080`. To create a local administrator in a fresh database:

```powershell
$env:ADMIN_USERNAME="admin"
$env:ADMIN_PASSWORD="Use-a-long-unique-password"
flask --app app create-admin
```

## OpenShift Console deployment using S2I

### Prerequisites

You need OpenShift console access and permission to create a project, build, deployment, service, route, Secret, and database resources. Your cluster must provide a Python 3.11 S2I builder image. You also need a PostgreSQL service from your organization's approved Operator/catalog or a managed PostgreSQL provider.

### 1. Create a project

1. Sign in to the OpenShift web console.
2. Switch to **Developer** perspective.
3. Open the project selector and choose **Create Project**.
4. Enter `jnpa-expense` and click **Create**.

### 2. Provision PostgreSQL

1. In Developer perspective, click **+Add**.
2. Open **Database** / **Developer Catalog** and search for **PostgreSQL**.
3. Select the PostgreSQL offering approved for your cluster and create a database, user, and password.
4. Wait until its pod is Ready. Record its service hostname, port (normally 5432), database name, username, and password.
5. If PostgreSQL is not available in the catalog, ask your OpenShift administrator for an approved database service or use managed PostgreSQL. Do not use pod-local SQLite for production.

### 3. Create application Secret

1. Switch to **Administrator** perspective.
2. Open **Workloads → Secrets** and ensure project `jnpa-expense` is selected.
3. Click **Create → Key/value secret**.
4. Name it `jnpa-app-secret`.
5. Add `SECRET_KEY` with a long random secret.
6. Add `DATABASE_URL` with this format, replacing every placeholder:
   `postgresql+psycopg://DB_USER:DB_PASSWORD@DB_HOST:5432/DB_NAME`
7. Click **Create**. URL-encode special characters in DB credentials and add TLS parameters if your database provider requires them. Never commit secrets to Git.

### 4. Import the application from Git (S2I)

1. Return to **Developer** perspective and select project `jnpa-expense`.
2. Click **+Add → Import from Git** (some versions show **From Git**).
3. Enter your Git repository URL, e.g. `https://github.com/YOUR-USERNAME/jnpa.git`.
4. If detection does not select Python, choose **Edit Import Strategy → Builder Image → Python**.
5. Select an available Python 3.11 builder image/tag from the console. The exact tag depends on cluster configuration; do not assume `python:3.11-ubi9` exists.
6. Set application/component name to `jnpa-expense`.
7. Choose **Deployment** and enable **Create a route to the application**.
8. If environment settings are shown, set `PORT=8080`.
9. Click **Create**. The `.s2i/environment` file selects `wsgi:app`; S2I installs packages from `requirements.txt`.

### 5. Attach the Secret to the deployment

If the Git import form did not allow environment variables:

1. Switch to **Administrator → Workloads → Deployments**.
2. Open deployment `jnpa-expense`.
3. Find **Environment** / **Edit environment**.
4. Add `SECRET_KEY` and `DATABASE_URL` from Secret `jnpa-app-secret` using the **Value from Secret** option.
5. Save and wait for the rollout.

### 6. Check build and pod status

1. Open **Developer → Topology**.
2. Click the `jnpa-expense` node and inspect its build status/logs.
3. Wait for build completion.
4. Confirm the application pod is **Running** and Ready.
5. For errors, inspect build logs, pod logs, and Events. Check builder availability, dependencies, DB URL, DNS, network access, and credentials.

### 7. Open in Chrome / Edge

1. In **Topology**, click the application node.
2. Open **Resources** and find **Routes**.
3. Click the route hostname or external-link icon.
4. The browser opens the application login page. Use the HTTPS route if TLS is configured.

A default user is **not** created. Create the administrator securely by running the Flask CLI command once with `ADMIN_USERNAME` and `ADMIN_PASSWORD` set, or use an approved secure provisioning method. Do not assume default credentials.

## Production cautions

- Use persistent PostgreSQL with backups. Do not store production data in SQLite inside the application container.
- Receipt uploads default to `/tmp/jnpa-uploads`, which is ephemeral. Before production, mount a PVC and set `UPLOAD_FOLDER` to its mount path, or use approved object storage.
- Add CSRF protection, rate limiting, database migrations (Flask-Migrate/Alembic), secure account provisioning, and a security review before exposing the app to real users.
- `db.create_all()` creates missing tables; it does not migrate schema changes.
- Review role permissions and approval rules before production.

## Troubleshooting

- **Build fails:** check build logs, root-level `requirements.txt`, and available Python builder tags.
- **Pod CrashLoopBackOff:** inspect pod logs; confirm `DATABASE_URL` and PostgreSQL connectivity.
- **Route 503:** ensure the pod is Ready and service target port is 8080.
- **Login fails:** no default account exists; provision an admin account securely.
- **Data disappears:** verify PostgreSQL persistence and durable receipt storage.
