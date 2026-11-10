# MediTrack — Hospital Management System

A small hospital management system, deployed to an AWS EC2 instance using
Docker. Written for this project rather than vendored from elsewhere.

| | |
|---|---|
| **Presentation tier** | React 19 + TypeScript (Vite), served by nginx |
| **Application tier** | Python / FastAPI JSON API, SQLAlchemy |
| **Database** | SQLite by default; PostgreSQL / RDS via `DATABASE_URL` |
| **Deployment** | Over AWS Systems Manager. No SSH, no inbound port 22. |
| **Session notes** | Stored in S3 (`ap-southeast-2`) |
| **Cloud** | AWS EC2 — `t3.micro`, Amazon Linux 2023 |
| **Sign in** | `admin` / `admin123` — change it immediately after first login |

> **Synthetic data only.** This system is shaped like one that would hold patient
> records, and it is deployed over plain HTTP on a public address with a known
> default password. That is acceptable for a demonstration with invented data
> and not acceptable for anything else. Before putting real patient information
> in it, put TLS in front, restrict who can reach it, and change the password.
> In India the DPDP Act applies to personal health data.

---

## What it does

The workflow of a small clinic, end to end:

- **Patients** — register with an auto-allocated medical record number (`MRN-00001`),
  search by name, MRN or phone, and view a full history on one page. Age is
  computed from date of birth. Known allergies are shown as a banner on the
  patient record and on every consultation, because that is the one detail you
  do not want buried in a field.
- **Doctors** — roster with specialisation, room, and a per-doctor consultation
  fee that pre-fills the billing on a visit.
- **Appointments** — book a patient with a doctor, browse any day, filter by
  status, and mark a booking as cancelled or a no-show. **Double-booking is
  refused**: slots are 20 minutes, and a clash reports who already holds the
  slot. Cancellations and no-shows release it.
- **Consultations** — the clinical record: symptoms, diagnosis, prescription,
  notes, follow-up date. Recording a visit against a booking marks that booking
  completed automatically. A walk-in can be recorded with no prior booking.
- **Billing** — a fee and payment status per consultation, an "unpaid only"
  filter, and total outstanding on the dashboard.
- **Session notes** — an append-only timeline of progress notes on a session,
  added after the initial write-up. Each note has a title, text, and optionally
  an attached document (lab report, scan). **The note text and the attachment
  both live in S3**, not in the database: the row holds only metadata and the
  object key. Notes cannot be edited or deleted — a clinical record that can be
  silently rewritten is not much of a record.
- **Dashboard** — patient and doctor counts, today's schedule, who is still to
  be seen, what is coming up, recent records, and money outstanding.

Authentication is deliberately plain: one account, username and password, a
signed session cookie. No roles, no tokens, no password reset. The one thing
not simplified away is that the password is **hashed with bcrypt** rather than
stored in the clear.

## Demo data

On an empty database the app seeds itself: 5 doctors across different
specialisations, 10 patients spanning ages 8 to 78 with varied blood groups and
allergies, 13 appointments positioned relative to today (some already completed,
one no-show, one cancelled, several upcoming), and 4 written-up consultations
with realistic diagnoses and prescriptions — one left unpaid so the outstanding
total is non-zero.

Seeding only runs when the patient table is empty, so restarting never
duplicates records or resurrects ones you deleted. Set `SEED_DEMO_DATA=false`
to start genuinely empty.

---

## Repository contents

| Path | Purpose |
|---|---|
| `app/` | **Application tier**: FastAPI JSON API, 24 endpoints. `models.py`, `schemas.py`, `api/`, `storage.py`. |
| `app/tests/` | 73 tests covering the auth gate, every resource, and the booking and validation rules. |
| `frontend/` | **Presentation tier**: React SPA plus the nginx configuration that serves it and proxies `/api`. |
| `docker-compose.yml` | Runs both tiers on one instance as two containers. |
| `infra/` | Scripts for the two-subnet VPC architecture in `REPORT.md` §3. Not run. |
| `bootstrap.sh` | Instance user-data. Swap, Docker, and the Compose and buildx CLI plugins. Pass it verbatim. |
| `deploy.sh` | Deploys both tiers over AWS Systems Manager. No SSH, no inbound port 22. |
| `REPORT.md` | Project report: problem, objectives, architecture, services, implementation, results. |

---

## Running it locally

Two processes. **Terminal 1** — the application tier (JSON API) on port 9000:

```bash
cd app
uv venv && uv pip install -e '.[dev]'
uv run uvicorn meditrack.main:app --reload --port 9000
```

**Terminal 2** — the presentation tier (React) on port 5173:

```bash
cd frontend
npm install
npm run dev
```

Open <http://127.0.0.1:5173> and sign in with `admin` / `admin123`.
The database is created at `app/data/meditrack.db`.

Vite proxies `/api` to port 9000. That is the same path-based forwarding nginx
does in the deployed stack, so the session cookie works identically in both —
there is no CORS configuration in development that would not exist in
production.

### Or run both as the deployed stack

Requires Docker:

```bash
echo "SECRET_KEY=$(head -c 32 /dev/urandom | base64 | tr -d '=+/')" > .env
docker compose up -d --build
```

Open <http://127.0.0.1>. Only the `web` container publishes a port; `api` is
reachable only on the compose network.

### Tests

```bash
cd app      && uv run pytest -q     # 73 tests
cd frontend && npm run typecheck    # strict TypeScript
cd frontend && npm run build        # production bundle
```

## Configuration

Every setting is an environment variable with a sensible default.

| Variable | Default | Notes |
|---|---|---|
| `APP_NAME` | `MediTrack` | Shown in the UI |
| `DATA_DIR` | `./data` | Where the SQLite file lives; `/data` in the container |
| `DATABASE_URL` | SQLite in `DATA_DIR` | Point at PostgreSQL if you outgrow SQLite |
| `SECRET_KEY` | generated per process | **Set this.** Unset means sessions die on restart |
| `SESSION_MAX_AGE` | `28800` (8h) | Session lifetime in seconds |
| `SEED_USERNAME` | `admin` | The one account |
| `SEED_PASSWORD` | `admin123` | Only used when first creating the account |
| `SEED_FULL_NAME` | `Dr. A. Menon` | Display name |
| `SEED_DEMO_DATA` | `true` | `false` to skip the demo records |
| `STORAGE_BACKEND` | `local` | `local` or `s3` |
| `LOCAL_STORAGE_DIR` | `<DATA_DIR>/objects` | Where the local driver writes |
| `S3_BUCKET` | — | Required when `STORAGE_BACKEND=s3` |
| `S3_PREFIX` | `session-notes` | Key prefix inside the bucket |
| `AWS_REGION` | — | Bucket region |
| `S3_ENDPOINT_URL` | — | For a non-AWS S3-compatible store (MinIO) |
| `S3_URL_TTL` | `300` | Presigned attachment URL lifetime, seconds |
| `MAX_ATTACHMENT_BYTES` | `10485760` | 10 MB |

`deploy.sh` generates a `SECRET_KEY` once into `.secret-key` and reuses it, so
redeploying does not sign you out. That file is gitignored — keep it.

---

## Object storage for session notes

Create a bucket in your own account (bucket names are globally unique, so
incorporate something unique such as your account id):

```
meditrack-session-notes-<account-id>
```

The scripts do not hardcode this, since the name embeds an account id. Record
it once and it is picked up from there:

```bash
echo meditrack-session-notes-<account-id> > .s3-bucket   # gitignored
```

It is configured with all public access blocked, SSE-S3 default encryption,
versioning enabled (so an overwritten or deleted note object is recoverable),
and a bucket policy denying any request not over TLS.

### Credentials

**There are none to manage.** The instance has an IAM role, `meditrack-instance`,
carrying exactly:

```json
{
  "Effect": "Allow",
  "Action": ["s3:PutObject", "s3:GetObject"],
  "Resource": "arn:aws:s3:::meditrack-session-notes-<account-id>/session-notes/*"
}
```

plus read access to `/meditrack/*` in Parameter Store and `AmazonSSMManagedInstanceCore`.
No delete, no listing, no other bucket, no other service. The SDK obtains
short-lived credentials from the instance metadata service, so no access key
exists on the instance.

Configuration lives in Parameter Store and is read by the instance at deploy
time:

| Parameter | Type |
|---|---|
| `/meditrack/secret-key` | SecureString — signs session cookies |
| `/meditrack/s3-bucket` | String |
| `/meditrack/s3-prefix` | String |
| `/meditrack/database-url` | SecureString — optional; set to use RDS |

To rotate the session key:

```bash
aws ssm put-parameter --name /meditrack/secret-key --type SecureString \
  --value "$(head -c 32 /dev/urandom | base64 | tr -d '=+/')" --overwrite
./deploy.sh
```

> If you run the application tier in a container, the IMDS hop limit must be
> at least 2. The default of 1 is enough for the host but not for a process one
> hop further away on a bridge network, and the resulting failure looks like a
> permissions problem rather than a networking one.

### How attachments are served

The bucket is private. Downloads are not proxied through the instance: the app
returns a 303 to a short-lived presigned URL and S3 serves the bytes directly,
which keeps large files off a 1 GiB box.

> Presigned URLs must be signed against the **regional** endpoint. Signed
> against the global `s3.amazonaws.com`, S3 answers with a 307 to the regional
> host, and because SigV4 signs the host the redirect invalidates the
> signature. `storage.py` sets `addressing_style: "virtual"` for this reason.

---

## Deploying

### Prerequisites

- AWS CLI v2, configured: `aws configure --profile <name>`
- `bash`, `curl`, `tar`. No Docker and no SSH client needed locally.

```bash
export AWS_PROFILE=<name> AWS_DEFAULT_REGION=ap-southeast-2
```

`deploy.sh` uses AWS Systems Manager, so no inbound SSH is needed and no
port 22 rule is required on the security group.

### 1. Allocate the Elastic IP first

```bash
ALLOC=$(aws ec2 allocate-address --domain vpc --query AllocationId --output text)
IP=$(aws ec2 describe-addresses --allocation-ids "$ALLOC" \
      --query 'Addresses[0].PublicIp' --output text)
echo "$IP" > .static-ip
echo "$IP"
```

### 2. Security group

Only port 80. Administration goes through Systems Manager, so there is no
inbound SSH rule and no key pair to manage.

```bash
VPC=$(aws ec2 describe-vpcs --query 'Vpcs[?IsDefault].VpcId' --output text)
SG=$(aws ec2 create-security-group --group-name meditrack-sg \
      --description "MediTrack web" --vpc-id "$VPC" --query GroupId --output text)

aws ec2 authorize-security-group-ingress --group-id "$SG" \
  --protocol tcp --port 80 --cidr 0.0.0.0/0
```

### 3. Instance role

The instance needs to reach S3, read its configuration, and be reachable by
Systems Manager. All three come from one role, so nothing is stored on the host.

```bash
BUCKET=meditrack-session-notes-<account-id>
ACCT=$(aws sts get-caller-identity --query Account --output text)

cat > /tmp/trust.json <<'EOF'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
 "Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}
EOF

aws iam create-role --role-name meditrack-instance \
  --assume-role-policy-document file:///tmp/trust.json

cat > /tmp/policy.json <<EOF
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":["s3:PutObject","s3:GetObject"],
  "Resource":"arn:aws:s3:::${BUCKET}/session-notes/*"},
 {"Effect":"Allow","Action":["s3:GetObject"],
  "Resource":"arn:aws:s3:::${BUCKET}/deploy/*"},
 {"Effect":"Allow","Action":["ssm:GetParameter","ssm:GetParameters"],
  "Resource":"arn:aws:ssm:ap-southeast-2:${ACCT}:parameter/meditrack/*"},
 {"Effect":"Allow","Action":["kms:Decrypt"],"Resource":"*",
  "Condition":{"StringEquals":{"kms:ViaService":"ssm.ap-southeast-2.amazonaws.com"}}}
]}
EOF

aws iam put-role-policy --role-name meditrack-instance \
  --policy-name meditrack-s3-session-notes --policy-document file:///tmp/policy.json

aws iam attach-role-policy --role-name meditrack-instance \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore

aws iam create-instance-profile --instance-profile-name meditrack-instance
aws iam add-role-to-instance-profile \
  --instance-profile-name meditrack-instance --role-name meditrack-instance
```

### 4. Store the configuration

```bash
aws ssm put-parameter --name /meditrack/secret-key --type SecureString \
  --value "$(head -c 32 /dev/urandom | base64 | tr -d '=+/')" --overwrite
aws ssm put-parameter --name /meditrack/s3-bucket --type String \
  --value meditrack-session-notes-<account-id> --overwrite
aws ssm put-parameter --name /meditrack/s3-prefix --type String \
  --value session-notes --overwrite
```

### 5. Launch

```bash
AMI=$(aws ssm get-parameter \
  --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
  --query 'Parameter.Value' --output text)

SUBNET=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC" \
  "Name=availability-zone,Values=ap-southeast-2a" \
  --query 'Subnets[0].SubnetId' --output text)

INSTANCE=$(aws ec2 run-instances \
  --image-id "$AMI" \
  --instance-type t3.micro \
  --security-group-ids "$SG" \
  --subnet-id "$SUBNET" \
  --iam-instance-profile Name=meditrack-instance \
  --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=16,VolumeType=gp3,DeleteOnTermination=true}' \
  --user-data "file://bootstrap.sh" \
  --metadata-options "HttpTokens=required,HttpPutResponseHopLimit=2" \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=meditrack}]' \
  --query 'Instances[0].InstanceId' --output text)

aws ec2 wait instance-running --instance-ids "$INSTANCE"
aws ec2 associate-address --instance-id "$INSTANCE" --allocation-id "$ALLOC"
```

> `HttpPutResponseHopLimit=2` is required. IMDSv2 token responses carry an IP
> hop limit, and the default of 1 is enough for the host but not for a process
> in a container one hop further away. Left at 1, the application cannot obtain
> credentials and the failure reads as a permissions error.

Wait for the bootstrap to finish — it installs Docker and the Compose and
buildx plugins:

```bash
aws ssm describe-instance-information \
  --filters "Key=InstanceIds,Values=$INSTANCE" \
  --query 'InstanceInformationList[0].PingStatus' --output text   # expect Online
```

### 6. Deploy

```bash
./deploy.sh
```

It finds the instance by its `Name=meditrack` tag, stages the source in S3,
and instructs the instance over Systems Manager to pull it, assemble its
configuration from Parameter Store, and bring the stack up. It then polls the
public URL and exits non-zero if the application does not answer.

### 7. Sign in and change the password

Open `http://$IP`, sign in with `admin` / `admin123`, then go to **Account** and
change it. The instance is publicly reachable on port 80.

---

## Operating it

No SSH. Administration goes through Systems Manager:

```bash
export AWS_PROFILE=new AWS_REGION=ap-southeast-2
INSTANCE=$(aws ec2 describe-instances --filters "Name=tag:Name,Values=meditrack" \
  "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)

# Interactive shell
aws ssm start-session --target "$INSTANCE"

# Or a one-off command
aws ssm send-command --instance-ids "$INSTANCE" \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["cd /opt/meditrack && docker compose ps"]'
```

Once in a session:

```bash
cd /opt/meditrack
docker compose ps                 # both tiers and their health
docker compose logs -f api        # application logs
docker compose logs -f web        # nginx access and error logs

# The API publishes no host port, by design. To reach it:
docker compose exec api python -c \
  "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:9000/healthz').read())"
```

Back up the database:

```bash
aws ssm send-command --instance-ids "$INSTANCE" \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["docker run --rm -v meditrack_meditrack-data:/d -v /tmp:/b alpine tar czf /b/backup.tar.gz -C /d ."]'
```

Then copy it off the instance via S3, since there is no SSH channel:

```bash
aws ssm send-command --instance-ids "$INSTANCE" \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["aws s3 cp /tmp/backup.tar.gz s3://meditrack-session-notes-<account-id>/deploy/backup.tar.gz --region ap-southeast-2"]'
aws s3 cp s3://meditrack-session-notes-<account-id>/deploy/backup.tar.gz .
```

## Updating after a change

```bash
./deploy.sh
```

Re-sends both tiers, rebuilds them on the instance and recreates the stack.
The `meditrack-data` volume is untouched, so the database survives.

Docker's layer cache lives on the instance, so an incremental change rebuilds
faster than the first run. A change under `frontend/src/` re-runs the Vite
build but reuses the `npm ci` layer; a change under `app/meditrack/` reuses the
pip layer.

## Tearing down

```bash
aws ec2 terminate-instances --instance-ids "$INSTANCE"
aws ec2 wait instance-terminated --instance-ids "$INSTANCE"
aws ec2 release-address --allocation-id "$ALLOC"
aws ec2 delete-security-group --group-id "$SG"
aws iam remove-role-from-instance-profile \
  --instance-profile-name meditrack-instance --role-name meditrack-instance
aws iam delete-instance-profile --instance-profile-name meditrack-instance
aws iam delete-role-policy --role-name meditrack-instance \
  --policy-name meditrack-s3-session-notes
aws iam detach-role-policy --role-name meditrack-instance \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam delete-role --role-name meditrack-instance
```

Release the Elastic IP: an allocated address not associated with a running
instance is billed.

## Known limitations

Deliberate, given the scope:

- **No TLS.** Traffic is plain HTTP. The first thing to fix for any real use.
- **One instance, one Availability Zone.** No redundancy; losing it loses the service.
- **SQLite on instance-local storage.** Fine for a single clinic's write volume;
  the data lives in a Docker volume on one EBS disk.
- **No automated backups.** The command above is manual.
- **One account, no roles.** A real system would separate reception, clinicians
  and administrators, and would keep an audit trail of who read which record.
- **No monitoring or alerting.** `/healthz` exists and Docker restarts the
  container, but nothing tells you if it is down.
