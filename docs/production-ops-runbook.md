# Production Operations & Deployment Runbook

This runbook describes the procedure to deploy, initialize, maintain, and verify a production instance of the Aegis Attendance Tracker System on a clean host machine.

---

## 1. System Requirements

*   **OS**: Linux (Ubuntu 22.04+ or Alpine Linux recommended)
*   **Hardware**: Min 4 vCPUs, 8 GB RAM, 20 GB free disk space (ONNX runtime inference runs on CPU by default).
*   **Dependencies**: Docker Engine 24+ and Docker Compose v2+.

---

## 2. Installation & Quickstart

To stand up a fully functional environment in under 15 minutes, perform the following steps:

### Step 2.1: Clone and Configure Environment
1.  Clone the repository to the host machine:
    ```bash
    git clone https://github.com/TetengDev/attendance-tracker-ai-app.git /opt/attendance-tracker
    cd /opt/attendance-tracker
    ```
2.  Create and configure your `.env` file based on `.env.example`:
    ```bash
    cp .env.example .env
    ```
3.  Set key configuration secrets inside `.env`:
    *   `BIOMETRIC_KEK`: The master key encryption key (format: `kek.<id>:<base64url-32-byte-key>`).
    *   `SECRET_KEY`: A cryptographically secure random string used for session hashes.
    *   `DOMAIN`: The hostname of your admin dashboard (e.g. `http://attendance.example.com`).
    *   `KIOSK_DOMAIN`: The hostname of your kiosk frontend (e.g. `http://kiosk.example.com`).

> [!IMPORTANT]
> To comply with browsers' **Secure Context** rules for camera access (`getUserMedia`), the `KIOSK_DOMAIN` must be accessed via HTTPS or loopback (`localhost`). Caddy will automatically provision Let's Encrypt certificates if `DOMAIN` and `KIOSK_DOMAIN` are set to real public subdomains.

### Step 2.2: Launch Services
Run the following command to compile the frontends and launch all services in the background:
```bash
docker compose -f infra/compose.yml up -d --build
```

Verify that all containers reach a `running` or `healthy` state:
```bash
docker compose -f infra/compose.yml ps
```

---

## 3. Database Seeding & Initialization

On a clean install, you must seed the initial owner account, default location, and generate device pairing tokens:

```bash
docker compose -f infra/compose.yml exec backend python -m backend.app.cli.seed
```

This creates the default super admin:
*   **Email**: `admin@example.test`
*   **Password**: `change-me-now`

---

## 4. Secure Backup & Restore Procedures

### Step 4.1: Database Dump (Backups)
Dump the database to a SQL file. **To satisfy DPA compliance, your backup script must never copy the KEK file or KEK environment variables to the same backup storage location.**

```bash
docker compose -f infra/compose.yml exec postgres pg_dump -U attendance -d attendance > backup_$(date +%F).sql
```

### Step 4.2: Backup Hardening Verification Test
To prove that your biometric database backups are secure against exfiltration, run this verification test:

1.  Restore the database backup file onto an isolated test machine:
    ```bash
    cat backup_xxxx-xx-xx.sql | docker exec -i new-postgres-container psql -U attendance -d attendance
    ```
2.  Start the backend application container **without** mounting the `BIOMETRIC_KEK` environment key or file.
3.  Observe backend startup errors.
    *   **Expected Behavior**: The container will fail to boot or log a `KeyConfigurationError` stating `BIOMETRIC_KEK is required`.
4.  If forced to start (bypassing boot assertions), attempt to access the face recognition index:
    *   **Expected Behavior**: The reload/match process will fail with `cryptography.exceptions.InvalidTag`, proving that the gallery embeddings and original images cannot be decrypted or loaded without the separate KEK.

---

## 5. Troubleshooting & Diagnostics

### WebSocket or API Connection Failure
*   **Symptom**: Kiosk shows "Disconnected" red banner or logs `OPTIONS 400 Bad Request`.
*   **Fix**: Confirm the CORS settings. The kiosk domain or local development ports must be included inside the `CORS_ALLOWED_ORIGINS` variable in `.env` (or config.py).

### Camera Access Denied on Kiosk
*   **Symptom**: Kiosk loads but camera displays a black screen or permissions error.
*   **Fix**: Ensure you are serving the Kiosk over HTTPS. Chrome and Safari block `getUserMedia` on non-localhost HTTP origins.
