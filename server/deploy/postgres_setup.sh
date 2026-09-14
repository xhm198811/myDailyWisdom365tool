#!/usr/bin/env bash
# =============================================================================
# TencentCloud Lighthouse - PostgreSQL bootstrap for daily-greeting-api
# Plan A: CloudBase runs the API, this box only runs PostgreSQL.
#
# Usage (as root):
#   bash postgres_setup.sh                     # auto-generate a 32-char password
#   bash postgres_setup.sh 'YourPassword32'    # use a specific password
#   INIT_SQL=/path/001_init.sql bash postgres_setup.sh
#
# Idempotent - safe to run repeatedly.
# NOTE: password is restricted to A-Za-z0-9 for shell/SQL quoting safety.
# =============================================================================
set -euo pipefail

PG_PORT=15432
PG_DB=greeting
PG_USER=greeting
INIT_SQL="${INIT_SQL:-./001_init.sql}"
MARK="# >>> managed by postgres_setup.sh"

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[0;32m[ok]\033[0m %s\n' "$*"; }
warn() { printf '\033[0;33m[!!]\033[0m %s\n' "$*"; }

# ---- 0. preflight ------------------------------------------------------------
if [ "$(id -u)" -ne 0 ]; then
    echo "Must run as root. Try: sudo bash postgres_setup.sh" >&2
    exit 1
fi

PASSWORD="${1:-}"
if [ -z "$PASSWORD" ]; then
    PASSWORD="$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32)"
    warn "No password supplied, generated one (shown at the end)."
else
    if [[ ! "$PASSWORD" =~ ^[A-Za-z0-9]+$ ]]; then
        echo "Password must be A-Za-z0-9 only (shell/SQL quoting safety)." >&2
        exit 1
    fi
fi

# ---- 1. install --------------------------------------------------------------
log "1/7 Installing PostgreSQL"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq postgresql postgresql-contrib

PGVER="$(ls -1 /etc/postgresql | sort -V | tail -n1)"
CONF_DIR="/etc/postgresql/${PGVER}/main"
CONF="${CONF_DIR}/postgresql.conf"
HBA="${CONF_DIR}/pg_hba.conf"
ok "PostgreSQL ${PGVER} installed, conf dir: ${CONF_DIR}"

# ---- 2. role + database ------------------------------------------------------
log "2/7 Creating role and database"
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${PG_USER}'" | grep -q 1; then
    sudo -u postgres psql -c "CREATE ROLE ${PG_USER} LOGIN PASSWORD '${PASSWORD}';"
fi
# always (re)set the password so re-runs converge
sudo -u postgres psql -c "ALTER ROLE ${PG_USER} WITH LOGIN PASSWORD '${PASSWORD}';"

if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${PG_DB}'" | grep -q 1; then
    sudo -u postgres createdb -O "${PG_USER}" -E UTF8 \
        --lc-collate=C --lc-ctype=C -T template0 "${PG_DB}"
fi
# CRITICAL: Lighthouse ships with UTC. Without this every timestamptz
# (holidays.day, weather_cache) is interpreted 8 hours off - silently.
sudo -u postgres psql -c "ALTER DATABASE ${PG_DB} SET timezone TO 'Asia/Shanghai';"
ok "role '${PG_USER}' and database '${PG_DB}' ready"

# ---- 3. hardening ------------------------------------------------------------
log "3/7 Hardening config (port ${PG_PORT}, TLS enforced)"
TS="$(date +%s)"
cp -n "${CONF}" "${CONF}.bak.${TS}" 2>/dev/null || true
cp -n "${HBA}"  "${HBA}.bak.${TS}"  2>/dev/null || true

sed -i "s/^#\?listen_addresses.*/listen_addresses = '*'/" "${CONF}"
sed -i "s/^#\?port = .*/port = ${PG_PORT}/" "${CONF}"
sed -i "s/^#\?password_encryption.*/password_encryption = scram-sha-256/" "${CONF}"

if grep -q "^#\?ssl = " "${CONF}"; then
    sed -i "s/^#\?ssl = .*/ssl = on/" "${CONF}"
else
    echo "ssl = on" >> "${CONF}"
fi

if ! grep -q "${MARK}" "${CONF}"; then
cat >> "${CONF}" <<EOF

${MARK}
shared_buffers = 256MB
effective_cache_size = 768MB
work_mem = 8MB
maintenance_work_mem = 64MB
max_connections = 50
EOF
fi

# postgres needs ssl-cert group to read the snakeoil cert
if ! id -nG postgres | grep -qw ssl-cert; then
    usermod -aG ssl-cert postgres
fi

# hostssl, NOT host -> plaintext connections are rejected outright
cat > "${HBA}" <<EOF
# local (unix socket)
local   all             postgres                                peer
local   all             all                                     peer
# remote: TLS required. hostssl (not host) rejects plaintext.
hostssl ${PG_DB}        ${PG_USER}      0.0.0.0/0               scram-sha-256
hostssl ${PG_DB}        ${PG_USER}      ::/0                    scram-sha-256
EOF

systemctl restart postgresql
systemctl enable postgresql >/dev/null 2>&1 || true
sleep 2
ok "restarted, listening on ${PG_PORT}"

# ---- 4. seed data ------------------------------------------------------------
log "4/7 Importing seed data"
export PGPASSWORD="${PASSWORD}"
CONN="postgresql://${PG_USER}:${PASSWORD}@127.0.0.1:${PG_PORT}/${PG_DB}?sslmode=require"
if [ -f "${INIT_SQL}" ]; then
    psql "${CONN}" -v ON_ERROR_STOP=1 -q -f "${INIT_SQL}"
    ok "imported ${INIT_SQL}"
else
    warn "not found: ${INIT_SQL} - skipped"
    warn "copy sql/001_init.sql here and re-run to import"
fi

# ---- 5. verify ---------------------------------------------------------------
log "5/7 Verifying"
TZ_NOW="$(psql "${CONN}" -tAc 'show timezone' | tr -d ' ')"
[ "${TZ_NOW}" = "Asia/Shanghai" ] \
    && ok "timezone = ${TZ_NOW}" \
    || warn "timezone = ${TZ_NOW} (expected Asia/Shanghai)"
psql "${CONN}" -tAc "select version()" | cut -d, -f1 | sed 's/^/    version  : /'
GCOUNT="$(psql "${CONN}" -tAc "select count(*) from public.greetings" 2>/dev/null || echo 'n/a')"
HCOUNT="$(psql "${CONN}" -tAc "select count(*) from public.holidays" 2>/dev/null || echo 'n/a')"
echo "    greetings : ${GCOUNT} (expect >= 50)"
echo "    holidays  : ${HCOUNT} (expect >= 40)"

# ---- 6. backup ---------------------------------------------------------------
log "6/7 Installing daily backup"
cat > /opt/pgbackup.sh <<EOF
#!/bin/bash
set -e
D=/opt/pgbackup
mkdir -p "\$D"
export PGPASSWORD='${PASSWORD}'
pg_dump -h 127.0.0.1 -p ${PG_PORT} -U ${PG_USER} -d ${PG_DB} -Fc \\
        -f "\$D/${PG_DB}-\$(date +%F).dump"
find "\$D" -name '*.dump' -mtime +7 -delete
EOF
chmod +x /opt/pgbackup.sh
( crontab -l 2>/dev/null | grep -v pgbackup.sh || true
  echo "0 3 * * * /opt/pgbackup.sh" ) | crontab -
ok "daily pg_dump at 03:00 -> /opt/pgbackup, 7 day retention"

# ---- 7. summary --------------------------------------------------------------
log "7/7 Done"
cat <<EOF

================================================================--
  DATABASE PASSWORD :  ${PASSWORD}
================================================================--

  Put these into BOTH  server/.env  AND  the CloudBase console
  (service -> env vars). Missing the second one is the classic
  trap: the API silently falls back to built-in greetings and
  still returns HTTP 200.

      DB_HOST=<this server public IP>
      DB_PORT=${PG_PORT}
      DB_NAME=${PG_DB}
      DB_USER=${PG_USER}
      DB_PASSWORD=${PASSWORD}
      DB_SSLMODE=require-no-verify
      DB_TIMEZONE=Asia/Shanghai

  REMAINING MANUAL STEPS
    1. TencentCloud console -> Lighthouse -> Firewall
       -> allow TCP ${PG_PORT}
       (source 0.0.0.0/0, or the CloudBase fixed egress IP if
        your environment can provision one)
    2. Redeploy the CloudBase service so it picks up new env vars
    3. GET /api/v1/today and confirm  "degraded": false
================================================================--
EOF
