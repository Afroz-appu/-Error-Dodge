# Error Dodge private deployment

The lowest-cost portfolio setup is the local demo with synthetic fixtures, SQLite, and keyword retrieval. It requires no model account. To demonstrate the PostgreSQL path privately, run the Compose stack on a Linux machine you control, with the web app bound to loopback. Use an SSH tunnel for remote access. This avoids exposing the API or database publicly and has no per-token provider cost. Hosting and storage charges depend on your chosen machine.

## Docker staging

Docker and Compose must be installed on the target. Prepare a private host directory for credentials. These Linux commands generate all values locally. The directory limits host access; individual file modes let the non-root container read its explicitly mounted files.

~~~bash
umask 077
mkdir -p .secrets
python3 - <<'PY'
from pathlib import Path
import secrets

root = Path(".secrets")
password = secrets.token_urlsafe(32)
values = {
    "db_password": password,
    "db_url": f"postgresql://error_dodge:{password}@postgres:5432/error_dodge",
    **{f"{role}_token": secrets.token_urlsafe(32) for role in ("viewer", "evaluator", "reviewer")},
}
for name, value in values.items():
    path = root / name
    with path.open("x", encoding="utf-8") as stream:
        stream.write(value)
    path.chmod(0o444)
PY
docker compose config --quiet
docker compose up --build -d
docker compose ps
curl -f http://127.0.0.1:8000/health/ready
~~~

The exclusive file creation prevents these commands from replacing existing credentials. Sign in with the appropriate token through the private browser session. Keep credentials outside source control, screenshots, and issue logs. Compose mounts each service's required secrets as files. Keep Gemini disabled for the portfolio run.

For a remote Linux host, forward the loopback service from your computer:

~~~bash
ssh -N -L 8000:127.0.0.1:8000 user@your-host
~~~

Open the dashboard at port 8000. For acceptance, sign in as viewer and reviewer in turn, run a synthetic benchmark, verify the citation and saved decision, and rerun the database-backed tests. Back up PostgreSQL before changing the database image or applying new migrations.

The Docker and Compose configuration were prepared and parsed, but no Docker runtime was available in the validation environment. Public hosting remains pending. Before public or multi-tenant use, replace shared tokens with an identity provider, add workspace scoping and individual audit identity, configure TLS and edge rate limiting, and verify backups and rollback. Existing SQLite data has no automatic import.

[Docker Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/) · [PostgreSQL advisory locks](https://www.postgresql.org/docs/current/explicit-locking.html)
