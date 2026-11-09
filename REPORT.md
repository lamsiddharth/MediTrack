# MediTrack — Cloud Deployment of a Hospital Management System

**Project report**

| | |
|---|---|
| **Application** | MediTrack — hospital management system (patients, appointments, clinical records, billing) |
| **Implementation** | Python 3.13, FastAPI, SQLAlchemy 2.0, server-rendered Jinja2 templates |
| **Cloud provider** | Amazon Web Services |
| **Region** | `ap-southeast-2` — Asia Pacific (Sydney) |
| **Availability Zones** | `ap-southeast-2a` (active), `ap-southeast-2b` (provisioned, idle) |
| **Architecture** | Three tiers: public presentation, private application, private data |

> **Status of this report.** The application is built, tested and running; the
> S3 object storage tier is provisioned and verified against the live service.
> The VPC, the two EC2 tiers and the RDS instance described in §3 are **designed
> and scripted but not provisioned** — no compute or database resources have
> been created. §5 states precisely which parts are which, and §6 reports
> results only for what was actually executed. Nothing in this document claims
> a measurement that was not taken.

---

## 1. Problem statement

A small clinic keeps its records on paper and in spreadsheets. That arrangement
fails in specific, predictable ways:

- **Records are not retrievable under time pressure.** A clinician needs a
  patient's allergy history in seconds, not after a search through a filing
  cabinet. A paper allergy note that is not in front of the clinician at the
  moment of prescribing is not a safety control.
- **The schedule has no integrity.** Two receptionists working from the same
  paper diary can book one doctor twice at the same time. Nothing prevents it
  and nothing detects it.
- **Clinical history is fragmented.** A patient's past diagnoses, prescriptions
  and follow-ups sit across separate documents with no single chronological
  view.
- **Documents are detached from the record they belong to.** A lab report
  arrives as a PDF by email and is filed somewhere unrelated to the visit that
  requested it.
- **There is no availability story.** A single filing cabinet in a single room
  is a single point of failure, and so is a single desktop PC with a
  spreadsheet on it.

Buying a commercial hospital information system solves the application problem
but introduces an infrastructure one: where does it run, who can reach it, where
does the data live, and what happens when a component fails. **That
infrastructure question is the subject of this project.** The application was
written specifically so that there was a realistic, non-trivial workload to
deploy, rather than a placeholder.

The deployment problem has a particular shape because the data is clinical:

- The database must not be reachable from the internet under any configuration
  error, not merely discouraged from being so.
- Documents are binary, variable in size, and must outlive the server that
  received them.
- Confidentiality is a design requirement rather than a feature, which rules
  out shortcuts such as making an object store public to simplify downloads.

---

## 2. Objectives

| # | Objective | How it is addressed |
|---|---|---|
| **O1** | Deploy a working hospital management application onto public cloud infrastructure | §5.1 — containerised FastAPI application |
| **O2** | Expose exactly one public entry point, and no more | §3.2 — only the presentation tier has a route to an Internet Gateway |
| **O3** | Place the application server and the database beyond reach of the internet | §3.3 — private subnets with no Internet Gateway route; NAT for egress only |
| **O4** | Use a managed relational database rather than a self-administered one | §4.3 — Amazon RDS for PostgreSQL |
| **O5** | Store clinical documents durably and independently of server lifetime | §4.4 — Amazon S3, versioned and encrypted |
| **O6** | Lay out the network so a move to multi-AZ requires no re-addressing | §3.5 — subnets in two AZs from the outset |
| **O7** | Enforce least privilege between tiers and towards AWS services | §3.4, §4.5 — security-group chaining; scoped IAM policy |
| **O8** | Keep the design reproducible rather than hand-built | §5.3 — provisioning as scripts under `infra/` |
| **O9** | Be explicit about what this design does *not* provide | §6.4, §7.2 — single-AZ, no TLS, no failover |

### 2.1 Out of scope

Stated deliberately, because a reader should not assume these were overlooked:

- **DNS.** No Route 53 hosted zone, no registered domain. The system is reached
  by the presentation tier's Elastic IP address. §3.6 explains how the tiers
  address each other without it.
- **Automatic failover.** Subnets exist in two zones; compute and the database
  run in one. §6.4 quantifies the exposure.
- **TLS.** Traffic is plain HTTP. §7.2 treats this as the first thing to fix and
  explains why it was not done here.
- **Horizontal scaling and load balancing.** One instance per tier.

---

## 3. System architecture

### 3.1 Overview

Three tiers, each in its own subnet class, each reachable only from the tier in
front of it.

```
                             Internet
                                 |
                                 | HTTP :80
                                 v
                    +------------------------+
                    |  Elastic IP            |   no Route 53: the address
                    |  (presentation tier)   |   itself is the entry point
                    +-----------+------------+
                                |
  VPC  10.20.0.0/16  ===========|=====================================
  ap-southeast-2                |
                                |
  +--- PUBLIC SUBNET -----------|-------------------+   +-- PUBLIC ----+
  |    10.20.1.0/24  (ap-southeast-2a)              |   | 10.20.2.0/24 |
  |                             v                   |   | (2b)         |
  |    +----------------------------------------+   |   |              |
  |    |  EC2  t3.micro   "frontend"            |   |   |   empty      |
  |    |  nginx reverse proxy                   |   |   |   (reserved) |
  |    |  - terminates the public connection    |   |   |              |
  |    |  - holds no code, no credentials       |   |   +--------------+
  |    |  - also the SSH bastion                |   |
  |    +------------------+---------------------+   |   +-- NAT GW ----+
  |                       |                         |   | in 2a public |
  |                       |  proxy_pass :9000       |   +------+-------+
  +-----------------------|-------------------------+          |
                          |                                    |
  route: 0.0.0.0/0 -> Internet Gateway                         |
  ==============================================================|========
  route: 0.0.0.0/0 -> NAT Gateway  (private subnets)            |
                          |                                    |
  +--- PRIVATE SUBNET ----|-------------------------+   +-- PRIVATE ---+
  |    10.20.11.0/24  (ap-southeast-2a)             |   | 10.20.12.0/24|
  |                       v                         |   | (2b)         |
  |    +----------------------------------------+   |   |              |
  |    |  EC2  t3.micro   "backend"             |   |   |  empty, but  |
  |    |  Docker: meditrack app  :9000          |   |   |  joined to   |
  |    |  no public IP, no IGW route            |   |   |  the RDS     |
  |    +--------+-------------------+-----------+   |   |  subnet group|
  |             |                   |               |   |              |
  |             | :5432             | HTTPS         |   +--------------+
  |             v                   |               |
  |    +------------------+         |               |
  |    |  RDS PostgreSQL  |         |               |
  |    |  db.t4g.micro    |         |               |
  |    |  single-AZ (2a)  |         |               |
  |    |  encrypted       |         |               |
  |    +------------------+         |               |
  +---------------------------------|---------------+
                                    |
                      S3 Gateway VPC Endpoint
                      (route-table entry, not NAT)
                                    |
                                    v
                       +--------------------------+
                       |  Amazon S3               |
                       |  session notes and       |
                       |  attachments             |
                       |  private, versioned,     |
                       |  SSE-S3 encrypted        |
                       +--------------------------+
```

### 3.2 Presentation tier — public subnet

One `t3.micro` in `10.20.1.0/24`, AZ `ap-southeast-2a`, with an Elastic IP.

It runs **nginx as a reverse proxy only**. It carries no application code, no
database credentials and no AWS credentials. Its jobs are:

1. Accept the public connection on port 80.
2. Forward it to the application tier on port 9000.
3. Act as the SSH bastion for administrative access to the private tier.

Concentrating public exposure in a component this thin is the point. If it is
compromised, the attacker gains a proxy — not the database credentials, not the
S3 keys, and not the clinical data.

A design note worth being explicit about: MediTrack is a **server-rendered**
application, so HTML is produced by the application tier and passed through the
proxy. This is not a browser-side single-page app calling a separate API. The
"frontend" instance is the presentation and edge tier, not a separate
client-side codebase. Describing it otherwise would misrepresent the system.

`nginx` is configured (`infra/bootstrap-frontend.sh`) to pass through the
original client details, because from the application's point of view every
request otherwise appears to originate from the proxy:

```nginx
proxy_set_header Host              $host;
proxy_set_header X-Real-IP         $remote_addr;
proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
```

It also exposes `/nginx-health`, answered by the proxy itself, so that a health
check can distinguish "the edge is up but the application is not" from "nothing
is up" — which is the first question to ask during an incident.

### 3.3 Application tier — private subnet

One `t3.micro` in `10.20.11.0/24`, AZ `ap-southeast-2a`. **No public IP
address.**

It runs the MediTrack container, published on port 9000. What makes this
instance private is not a firewall rule but the **absence of a route**: its
subnet's route table has no entry pointing at the Internet Gateway. An inbound
packet from the internet has no path to it. A security-group mistake alone
cannot expose it; the routing table would have to be changed as well.

It still needs outbound access — operating-system patches, and Docker Hub during
an image build. That is provided by the **NAT Gateway**, which lives in the
public subnet and performs source translation for outbound connections only. A
NAT Gateway does not accept unsolicited inbound connections; there is no port
forwarding to configure and therefore none to misconfigure.

### 3.4 Data tier — private subnet

**Amazon RDS for PostgreSQL**, `db.t4g.micro`, 20 GB gp3, storage encrypted.

| Property | Value |
|---|---|
| Region | `ap-southeast-2` (Asia Pacific, Sydney) |
| Availability Zone | `ap-southeast-2a` |
| Subnet group | `10.20.11.0/24` (2a) **and** `10.20.12.0/24` (2b) |
| Multi-AZ | **No** — single instance, no standby |
| Publicly accessible | **No** |
| Automated backups | 7-day retention, 17:00–18:00 UTC window |
| Deletion protection | Enabled |

RDS requires a DB subnet group spanning **at least two** Availability Zones even
for a single-AZ instance. The group therefore covers both private subnets, while
the instance itself is pinned to `ap-southeast-2a`. This is the reason the
second zone's subnets exist at all at this stage, and it means enabling Multi-AZ
later is a single modification rather than a network redesign.

**Security-group chaining** is what keeps each tier isolated. Rules reference
*other security groups* rather than CIDR ranges, so they remain correct when an
instance is replaced and given a different address:

| Security group | Port | Source | Effect |
|---|---|---|---|
| `sg-frontend` | 80 | `0.0.0.0/0` | the one public entry point |
| `sg-frontend` | 22 | admin `/32` | administrative access |
| `sg-backend` | 9000 | **`sg-frontend`** | only the proxy may reach the app |
| `sg-backend` | 22 | **`sg-frontend`** | bastion hop only |
| `sg-database` | 5432 | **`sg-backend`** | only the app may reach the database |

The database accepts connections from exactly one source, identified by group
membership rather than by address.

### 3.5 Why two Availability Zones with one deployment

Subnets are created in both `ap-southeast-2a` and `ap-southeast-2b`. Compute and
the database run only in `2a`. This is a deliberate cost decision, not an
oversight, and it is honest to call it what it is: **there is no failover. Loss
of `ap-southeast-2a` is loss of the service.**

What the idle second zone buys, for no running cost:

- A `/16` with subnets already addressed and routed in both zones, so adding
  capacity later needs no renumbering.
- An RDS subnet group that already satisfies the Multi-AZ precondition.
- A documented, single-parameter path to higher availability
  (`--multi-az`, plus a second application instance behind a load balancer).

Empty subnets cost nothing. A NAT Gateway, a second instance and an RDS standby
all do, which is why only the subnets exist now.

### 3.6 How the tiers address one another without Route 53

This is the question the architecture has to answer most carefully, since there
is no DNS service in the design.

**Users → presentation tier.** By **Elastic IP**. An Elastic IP survives
instance stop/start, so the published address is stable without DNS. nginx is
configured with `server_name _` to answer for any `Host` header, since there is
no hostname to match on.

**Presentation → application tier.** Over the **private IPv4 address**, inside
the VPC. Traffic is routed by the VPC's implicit router and never touches the
Internet Gateway, the NAT Gateway, or the public internet. Three ways to obtain
that address, in increasing robustness:

1. *Read the private IP after launch and substitute it into the nginx config.*
   Simple, and what `infra/40-instances.sh` does. Brittle: replacing the
   instance changes the address and the proxy must be reconfigured.
2. *Use the VPC-provided internal DNS name* — for example
   `ip-10-20-11-23.ap-southeast-2.compute.internal`. This works because the VPC
   has `enableDnsSupport` and `enableDnsHostnames` set, and it is resolved by
   the **AWS-provided VPC resolver**, which is not Route 53 and needs no hosted
   zone. The name is still derived from the address, so it changes too.
3. **Recommended: assign a fixed private IP at launch.** The application tier is
   launched with `--private-ip-address 10.20.11.10`, chosen from its subnet.
   The address is then a property of the architecture rather than of a
   particular instance, and nginx can hard-code it. A replacement instance
   launched with the same address needs no proxy reconfiguration.

   This removes the need for service discovery entirely at this scale. The
   correct answer at larger scale is an internal load balancer or Route 53
   private hosted zone, but both add a component that one application instance
   does not justify.

**Application → database.** By the **RDS endpoint DNS name**, for example
`meditrack-db.abc123.ap-southeast-2.rds.amazonaws.com`. This resolves through
the VPC resolver to a private address within the DB subnet group. No Route 53
configuration is involved — RDS endpoints resolve inside the VPC by default.
Using the endpoint name rather than an IP matters here: were Multi-AZ enabled, a
failover changes the address the name points to, and anything holding a cached
IP would break.

**Application → S3.** Through an **S3 Gateway VPC Endpoint**. This installs a
prefix-list route in the private route table, so requests to S3 travel over the
AWS network directly instead of out through the NAT Gateway. Two consequences
that matter:

- **Cost.** NAT Gateways charge per gigabyte processed. Clinical attachments are
  the largest objects the system handles, and they would otherwise pay that
  charge in both directions.
- **Dependency.** The core feature of storing a clinical document no longer
  depends on the NAT Gateway being healthy.

**Administrator → application tier.** By SSH through the presentation tier as a
bastion, which needs no inbound rule on the private instance beyond one
referencing `sg-frontend`:

```bash
ssh -J ec2-user@<frontend-elastic-ip> ec2-user@10.20.11.10
```

### 3.7 Request path, end to end

A clinician opening a patient record:

```
browser
  --> HTTP :80 to Elastic IP
  --> IGW --> public subnet --> nginx (frontend, 10.20.1.x)
  --> proxy_pass --> private subnet --> app :9000 (backend, 10.20.11.10)
      |
      |-- SQL :5432 --> RDS (private, 2a)        patient, appointment, billing rows
      |
      '-- HTTPS via S3 Gateway Endpoint --> S3   note text and attachments
  <-- rendered HTML back through nginx
```

An attachment download does **not** follow the return path. The application
issues a 303 redirect to a short-lived presigned S3 URL and the browser fetches
the object from S3 directly. The bucket stays private, and a large file never
traverses either the application instance or the proxy — which matters on
`t3.micro` instances.

---

## 4. Cloud services used

| Service | Role | Configuration |
|---|---|---|
| **Amazon VPC** | Network isolation | `10.20.0.0/16`, four subnets across two AZs |
| **Internet Gateway** | Public inbound and outbound | Attached; default route for public subnets only |
| **NAT Gateway** | Private outbound only | In public subnet `2a`, with its own Elastic IP |
| **Route tables** | Separate public and private routing | Public → IGW; private → NAT + S3 endpoint |
| **Security groups** | Stateful per-tier firewalls | Chained by group reference, §3.4 |
| **Amazon EC2** | Both compute tiers | 2 × `t3.micro`, Amazon Linux 2023 |
| **Elastic IP** | Stable public address without DNS | One for the frontend, one for the NAT |
| **Amazon RDS** | Managed PostgreSQL | `db.t4g.micro`, single-AZ, encrypted, 7-day backups |
| **Amazon S3** | Clinical documents | Private, versioned, SSE-S3, TLS-only policy |
| **S3 Gateway VPC Endpoint** | Keep S3 traffic off NAT | Prefix-list route in the private table |
| **AWS IAM** | Least-privilege service access | One user, two S3 actions, one prefix |

### 4.1 Why EC2 and not a container service

ECS or EKS would remove instance management. Both were rejected for this scale:
EKS has a fixed control-plane charge larger than the entire rest of this
deployment, and ECS on Fargate would still require the same VPC, subnets,
routing and security groups — the parts this project is actually about — while
making the compute layer harder to inspect while learning. EC2 keeps the
networking visible, which is the point.

### 4.2 Why RDS and not PostgreSQL on the instance

Running PostgreSQL on the application instance would be cheaper and is
genuinely tempting at this size. RDS was chosen for three things that are
tedious to build and easy to get wrong: **automated backups with
point-in-time recovery**, **encryption at rest** without manual key handling,
and **a single-flag path to Multi-AZ**. For clinical data, losing the database
is the worst outcome in the system, and backups one does not have to remember to
run are worth the premium.

The application is database-agnostic: SQLAlchemy with no engine-specific SQL,
enums stored as `VARCHAR` rather than native PostgreSQL types, and all
SQLite-specific code guarded. The same image runs against SQLite locally and
RDS in the VPC with only `DATABASE_URL` changing.

### 4.3 Why S3 for clinical documents

Clinical attachments are the wrong shape for both a relational database and an
instance disk. In RDS they would inflate every backup and consume provisioned
storage priced far above object storage. On the instance's EBS volume they would
die with the instance and sit outside the backup regime entirely.

S3 gives eleven-nines durability, versioning, and a lifetime independent of any
server. The bucket is configured:

| Setting | Value | Reason |
|---|---|---|
| Block Public Access | all four flags on | clinical data must not be reachable anonymously, even by accident |
| Default encryption | SSE-S3 (AES256), bucket keys | encryption at rest without key management |
| Versioning | enabled | an overwritten or deleted object is recoverable |
| Bucket policy | deny `aws:SecureTransport = false` | rejects any non-TLS request outright |

### 4.4 Object layout

```
s3://meditrack-session-notes-808122334310/
  session-notes/
    consultations/<consultation-id>/
      notes/<random-uid>/
        body.txt                  note text
        attachment/<filename>     optional document
```

The per-note component is a random UUID rather than a database id. Keys
therefore do not depend on database sequence values, which keeps the two stores
independent and means an object key cannot be guessed by incrementing a number.

### 4.5 IAM and the credential problem

The application needs exactly two S3 actions on one prefix:

```json
{
  "Effect": "Allow",
  "Action": ["s3:PutObject", "s3:GetObject"],
  "Resource": "arn:aws:s3:::meditrack-session-notes-808122334310/session-notes/*"
}
```

No delete, no listing, no other prefix, no other bucket, no other service. If
the application tier were compromised, the reachable blast radius is read and
write on that one prefix.

**On an EC2 application tier this should be an IAM instance role**, so no secret
is ever stored: the instance obtains short-lived credentials from the instance
metadata service and the SDK rotates them automatically. That is what this
architecture specifies.

This is worth flagging as a genuine constraint discovered during the project:
an **earlier deployment of a different application used AWS Lightsail, which
does not support IAM instance roles** — there is no instance profile to attach.
Object storage from a Lightsail instance requires long-lived static access keys
placed on the host, which is materially worse: a file on a public-facing server
that does not expire. This was one of the reasons the architecture described
here uses EC2 within a VPC rather than Lightsail.

---

## 5. Implementation

### 5.1 Application — implemented and tested

Approximately 3,000 lines in `app/meditrack/` — 2,169 of Python and 869 of
templates — plus 67 tests.

| Module | Responsibility |
|---|---|
| `models.py` | Six tables: `users`, `patients`, `doctors`, `appointments`, `consultations`, `session_notes` |
| `db.py` | Engine and session handling; SQLite pragmas or PostgreSQL pooling by URL |
| `security.py` | bcrypt hashing, session cookie, login dependency |
| `storage.py` | Object-storage abstraction with `local` and `s3` drivers |
| `seed.py` | Schema creation, login account, demo data |
| `routes/` | `auth`, `dashboard`, `patients`, `doctors`, `appointments`, `consultations`, `notes` |
| `templating.py` | Jinja2 environment and formatting filters |

Functionality delivered:

- **Patients** — registration with auto-allocated medical record numbers
  (`MRN-00001`), search by name, MRN or phone, age derived from date of birth,
  and a consolidated history page. Known allergies are rendered as a banner on
  the patient record and on every consultation, addressing the safety failure
  identified in §1.
- **Doctors** — roster with specialisation, room and per-doctor consultation fee
  that pre-fills billing.
- **Appointments** — day-by-day browsing, status filtering, cancellation and
  no-show marking. **Double-booking is refused** across a 20-minute slot window,
  with an error naming the patient already holding the slot. Cancelled and
  no-show bookings release it. This directly addresses the schedule-integrity
  failure in §1.
- **Consultations** — symptoms, diagnosis, prescription, notes, follow-up date.
  Recording a visit against a booking completes that booking automatically.
  Walk-ins can be recorded with no prior appointment.
- **Session notes** — an append-only timeline of progress notes added after the
  initial write-up, each with optional document attachment. **Both the note text
  and the attachment are stored in S3**; the database row holds only metadata
  and the object key. Notes cannot be edited or deleted: a clinical record that
  can be silently rewritten is not much of a record.
- **Billing** — fee and payment status per consultation, unpaid filter, and
  outstanding totals on the dashboard.
- **Authentication** — single account, username and password, signed session
  cookie. Deliberately minimal, with three things not simplified away: bcrypt
  hashing, an identical error for unknown-user and wrong-password so the form
  cannot be used to enumerate usernames, and a `?next=` parameter restricted to
  relative paths so it cannot redirect off-site after login.

### 5.2 Storage abstraction

Two drivers behind one interface (`storage.py`), selected by
`STORAGE_BACKEND`:

- `local` — a directory on disk. The default, so the application and its whole
  test suite run with no AWS account. Essential for development and CI.
- `s3` — the deployed path.

Nothing above this module knows which is in use. This is what allowed the S3
integration to be tested exhaustively offline against `moto`, and then verified
separately against the real service.

### 5.3 Infrastructure as scripts — written, not executed

`infra/` contains idempotent provisioning scripts. **None have been run.** They
are the configuration deliverable and the reproducible definition of §3:

| File | Creates |
|---|---|
| `00-config.sh` | Shared variables: region, AZs, CIDRs, instance classes |
| `10-network.sh` | VPC, four subnets, IGW, NAT Gateway, route tables, S3 endpoint |
| `20-security-groups.sh` | The three chained security groups of §3.4 |
| `30-database.sh` | DB subnet group across both AZs, single-AZ RDS instance |
| `bootstrap-frontend.sh` | User-data: nginx reverse proxy configuration |
| `bootstrap-backend.sh` | User-data: swap and Docker |

Each script finds existing resources by `Name` tag and reuses them, so a partial
run can be repeated safely. Resource IDs are recorded in `infra/state.env` for
later scripts to consume.

### 5.4 Container image

Single-stage, `python:3.13-slim`. The application is Python with server-rendered
templates, so there is **no frontend build toolchain** — no Node, no bundler, no
asset pipeline. The practical consequence is large: the image builds in a minute
or two on a `t3.micro`, where a comparable application with a JavaScript build
step needed roughly 4 GB of memory and tens of minutes on the same hardware.

The container runs as a non-root user (uid 10001) and declares a `HEALTHCHECK`
against `/healthz`.

### 5.5 Deployment mechanism

`deploy.sh` sends the source to the instance over SSH, builds the image there,
and replaces the container. Notable properties:

- **No container registry.** Only source crosses the network — under a megabyte,
  rather than the several hundred a built image would be. Deployment is not
  gated on upload bandwidth, and no registry has to be provisioned or paid for.
- **No AWS credentials on the deploying machine's path into the instance.**
- **Verification, not optimism.** It polls `/healthz` and exits non-zero if the
  application does not become healthy, rather than reporting success because a
  command returned.
- **Data volumes are never removed**, so replacing the container cannot destroy
  the database.

---

## 6. Results

### 6.1 What was executed and verified

**Application test suite — 67 tests, all passing.**

```
$ cd app && uv run pytest -q
...................................................................
67 passed in 42.73s
```

Coverage is behavioural rather than incidental:

| Area | Tests verify |
|---|---|
| Authentication | every page redirects when unauthenticated; wrong password rejected; unknown user and wrong password are indistinguishable; `?next=` cannot redirect off-site |
| Patients | registration allocates sequential MRNs; future and malformed dates of birth rejected; search matches name, MRN and phone |
| Appointments | booking succeeds; same doctor in the same slot refused; a 10-minute offset still refused as overlapping; a different doctor at the same time allowed; 25 minutes later allowed |
| Consultations | diagnosis required; negative fee rejected; recording a visit completes its appointment |
| Storage | local and S3 drivers round-trip; traversal in object keys and filenames neutralised; oversized and disallowed attachment types rejected; an attachment cannot be fetched through a different consultation |
| Failure handling | a storage outage mid-write records no database row; a note whose object has vanished degrades in place rather than failing the page |

**S3 integration — verified against the live service.** Not mocked:

```
PUT/GET note body          : OK
presigned host             : meditrack-session-notes-808122334310.s3.ap-southeast-2.amazonaws.com
fetch via presigned URL    : OK
content-disposition        : attachment; filename="Lab_Report.pdf"
```

**End-to-end through the running application.** A progress note with a PDF
attachment was added through the web interface. Both objects appeared in S3:

```
session-notes/consultations/1/notes/5b596c1e.../body.txt                85 B
session-notes/consultations/1/notes/5b596c1e.../attachment/bloods.pdf   48 B
```

The note body was then read back from S3 and rendered on the consultation page,
and the attachment downloaded via presigned URL matched the uploaded file byte
for byte.

**Bucket configuration — confirmed by inspection:**

```
public access block : BlockPublicAcls, IgnorePublicAcls,
                      BlockPublicPolicy, RestrictPublicBuckets  = all true
encryption          : AES256
versioning          : Enabled
region              : ap-southeast-2
```

**Application running locally**, seeded and serving: 10 patients, 5 doctors,
13 appointments positioned relative to the current date, 4 written-up
consultations, and a non-zero outstanding balance.

**RDS compatibility — verified without an instance.** A PostgreSQL
`DATABASE_URL` produces a correctly configured engine (`psycopg` driver,
`QueuePool` of 5, pre-ping enabled) without contacting a server, confirming the
application is ready for the data tier.

### 6.2 What was not executed

Stated plainly, because the distinction is the difference between a report and a
claim:

| Component | Status |
|---|---|
| S3 bucket, IAM policy | **Provisioned and verified** |
| Application, tests, local run | **Implemented and verified** |
| VPC, subnets, IGW, NAT, routes | Scripted, **not provisioned** |
| EC2 presentation and application tiers | Scripted, **not provisioned** |
| RDS instance | Scripted, **not provisioned** |
| nginx proxy configuration | Written, **not exercised against a live backend** |

No latency, throughput or availability figures are reported, because no such
measurement was taken. Any number here would be invented.

### 6.3 Problems encountered

Three defects were found by testing the S3 feature, each of which would have
reached users:

1. **Empty file input returned HTTP 422.** Declaring the upload as a typed
   `UploadFile` parameter made FastAPI reject every note saved without choosing
   a file, because browsers always submit a file input — as a part with an empty
   filename. Fixed by reading the form directly.
2. **The fix then silently discarded all attachments.** `request.form()` yields
   `starlette.datastructures.UploadFile`, and `fastapi.UploadFile` is a
   *subclass* of it, so an `isinstance` check against the latter never matched.
   Notes saved successfully with the attachment dropped — the worst failure
   mode, because nothing reported an error.
3. **Presigned URLs returned 403.** boto3 signed them against the global
   `s3.amazonaws.com` endpoint. For a bucket outside `us-east-1` that endpoint
   answers with a 307 redirect to the regional host, and because SigV4 signs the
   `Host` header, following the redirect invalidates the signature. Fixed with
   `addressing_style: "virtual"`.

A fourth problem was environmental: **Cloudflare WARP intercepts outbound SSH**,
causing port 22 to time out, and simultaneously causes `checkip` to report a
rotating Cloudflare address rather than the administrator's own — which would
place the wrong `/32` in the administrative security-group rule.
`20-security-groups.sh` warns about this, and `deploy.sh` names an active tunnel
as the first thing to check when SSH fails.

A test-isolation defect was also found and fixed: the password-change test left
the shared account's password altered, breaking every test that ran after it.

### 6.4 Availability assessment

With compute and database in `ap-southeast-2a` only:

| Failure | Consequence | Recovery |
|---|---|---|
| Application instance fails | Total outage | Manual relaunch and redeploy |
| Presentation instance fails | Total outage | Manual relaunch |
| RDS instance fails | Total outage, data intact | Restore from automated backup |
| **AZ `ap-southeast-2a` fails** | **Total outage** | **Manual rebuild in `2b`** |
| NAT Gateway fails | Service continues; S3 unaffected (gateway endpoint); OS updates and image builds fail | Recreate |
| S3 unavailable | Note bodies unreadable, rendered as unavailable in place; rest of application works | Wait |

The last row is the only graceful degradation in the system, and it exists
because it was deliberately built and tested. Everything above it is a hard
outage. That is the honest cost of a single-AZ deployment, and §7.2 gives the
remediation.

### 6.5 Indicative monthly cost

`ap-southeast-2`, on-demand, excluding free-tier credits. Approximate.

| Item | ~USD/month |
|---|---|
| EC2 `t3.micro` × 2 | 19 |
| RDS `db.t4g.micro`, 20 GB gp3, single-AZ | 17 |
| **NAT Gateway** (hourly + data processing) | **35** |
| Elastic IPs × 2 (one attached, one on NAT) | 4 |
| S3 storage and requests (low volume) | <1 |
| EBS root volumes | 3 |
| **Total** | **≈ 78** |

The NAT Gateway is the largest single line — more than either compute tier.
Two observations follow. First, the S3 Gateway Endpoint is not merely a
networking nicety: it removes per-gigabyte NAT processing charges on the
largest objects the system handles. Second, if cost mattered more than
architectural cleanliness at this scale, a NAT *instance* on a `t3.nano`, or
placing the application tier in the public subnet with no inbound rules, would
each remove most of that line — at the price of self-managed NAT or a weaker
isolation story respectively. The managed NAT Gateway was kept because the
isolation property in §3.3 is the substance of this design.

---

## 7. Conclusion

### 7.1 What was achieved

A hospital management application was written, tested and run, and a three-tier
AWS architecture was designed and expressed as reproducible provisioning
scripts. Against the objectives of §2:

| | Objective | Outcome |
|---|---|---|
| O1 | Deploy a working application | Application built and verified; VPC deployment scripted, not provisioned |
| O2 | One public entry point | Achieved in design: only the public route table has an IGW route |
| O3 | App and database unreachable from the internet | Achieved in design: private subnets with NAT egress only |
| O4 | Managed database | RDS PostgreSQL specified; application verified compatible |
| O5 | Durable document storage | **Achieved and verified** — S3, private, versioned, encrypted |
| O6 | Multi-AZ-ready addressing | Achieved in design: subnets in both zones, RDS subnet group spanning them |
| O7 | Least privilege | **Achieved** — IAM policy provisioned; security-group chaining designed |
| O8 | Reproducible provisioning | Achieved: `infra/` scripts, idempotent |
| O9 | Be explicit about gaps | §6.2, §6.4, §7.2 |

The central design decision is the one in §3.3: the application tier is private
because its **route table has no path to an Internet Gateway**, not because a
firewall rule denies traffic. Routing absence is a stronger guarantee than rule
presence — a security-group error alone cannot expose it. Expressing that
property correctly, and understanding why it is stronger, was the main learning
outcome of the project.

### 7.2 Limitations and what to do next

In the order a real deployment should address them:

1. **No TLS.** Traffic, including the login password, crosses the internet in
   clear text. This is the first thing to fix and the reason the system holds
   only synthetic data. Without a domain name there is no public CA path, so the
   realistic options are a registered domain plus an ACM certificate on an
   Application Load Balancer, or a self-signed certificate for a closed
   demonstration. **No real patient data should be entered until this is done.**
2. **Default credentials.** The seeded account is `admin` / `admin123`, which is
   documented and therefore public. It must be changed at first login, and the
   application logs a warning at startup while it remains unchanged.
3. **Single Availability Zone.** Remediation in increasing order of cost:
   enable Multi-AZ on RDS (one flag, roughly doubling database cost); add a
   second application instance in `2b`; place an Application Load Balancer
   across both. The network already accommodates all three.
4. **Static credentials where instance roles are unavailable.** Resolved in this
   architecture by using EC2 rather than Lightsail, so the application tier can
   use an instance role and store no secret at all.
5. **Database password handling.** Generated locally into a gitignored file.
   It belongs in AWS Secrets Manager, retrieved at runtime via the instance
   role, so that it is never written to disk or into a launch script.
6. **One account, no roles.** A real system would separate reception,
   clinicians and administrators, and keep an audit trail of who read which
   record. For clinical data, read access is as significant as write access, and
   nothing here records it.
7. **No monitoring or alerting.** `/healthz` and `/nginx-health` exist and
   Docker restarts a failed container, but nothing reports an outage. CloudWatch
   alarms on instance and RDS health would be the minimum.

### 7.3 Reflection

The most useful lesson was not architectural but methodological. Three of the
defects in §6.3 — the 422 on an empty file input, the silently dropped
attachments, and the 403 on presigned URLs — were invisible to reasoning about
the code and surfaced only by exercising it against the real service. The second
is the instructive one: it did not fail loudly. Notes saved successfully with
the attachment discarded, and only a test that asserted the stored object
existed caught it.

A deployment that has not been exercised is a hypothesis, not a result. That is
why §6.2 separates what ran from what was only written, rather than presenting
the design as though it had been measured.

---

## Appendix A — Repository contents

```
hospital-project/
├── README.md                  setup and execution instructions
├── REPORT.md                  this document
├── deploy.sh                  build-on-instance deployment over SSH
├── bootstrap.sh               single-instance user-data (simple deployment)
├── infra/                     three-tier VPC provisioning (written, not run)
│   ├── 00-config.sh           region, AZs, CIDRs, instance classes
│   ├── 10-network.sh          VPC, subnets, IGW, NAT, routes, S3 endpoint
│   ├── 20-security-groups.sh  chained per-tier security groups
│   ├── 30-database.sh         RDS subnet group and instance
│   ├── bootstrap-frontend.sh  nginx reverse proxy user-data
│   └── bootstrap-backend.sh   Docker user-data
└── app/
    ├── Dockerfile             single-stage Python image
    ├── pyproject.toml         pinned dependencies
    ├── meditrack/
    │   ├── config.py          environment configuration
    │   ├── db.py              engine, session, per-dialect tuning
    │   ├── models.py          six tables
    │   ├── security.py        bcrypt and session auth
    │   ├── storage.py         local and S3 object-storage drivers
    │   ├── seed.py            schema, account, demo data
    │   ├── main.py            application assembly
    │   ├── templating.py      Jinja2 environment and filters
    │   ├── routes/            seven route modules
    │   ├── templates/         15 templates
    │   └── static/style.css   stylesheet
    └── tests/                 67 tests
```

## Appendix B — Configuration reference

All settings are environment variables with defaults; none are required for a
local run.

| Variable | Default | Purpose |
|---|---|---|
| `APP_NAME` | `MediTrack` | Name shown in the interface |
| `DATA_DIR` | `./data` | SQLite file location; `/data` in the container |
| `DATABASE_URL` | SQLite in `DATA_DIR` | Set to `postgresql+psycopg://…` for RDS |
| `SECRET_KEY` | generated per process | Signs session cookies; **set in deployment** |
| `SESSION_MAX_AGE` | `28800` | Session lifetime, seconds |
| `SEED_USERNAME` | `admin` | The single account |
| `SEED_PASSWORD` | `admin123` | Used only when first creating the account |
| `SEED_DEMO_DATA` | `true` | `false` for an empty database |
| `STORAGE_BACKEND` | `local` | `local` or `s3` |
| `LOCAL_STORAGE_DIR` | `<DATA_DIR>/objects` | Local driver root |
| `S3_BUCKET` | — | Required when `STORAGE_BACKEND=s3` |
| `S3_PREFIX` | `session-notes` | Key prefix within the bucket |
| `AWS_REGION` | — | Bucket region |
| `S3_ENDPOINT_URL` | — | For S3-compatible stores such as MinIO |
| `S3_URL_TTL` | `300` | Presigned URL lifetime, seconds |
| `MAX_ATTACHMENT_BYTES` | `10485760` | 10 MB attachment cap |

## Appendix C — Execution instructions

Full detail is in `README.md`. In brief:

**Run locally** (no AWS account needed):

```bash
cd app
uv venv && uv pip install -e '.[dev]'
uv run uvicorn meditrack.main:app --reload --port 8000
```

Open <http://127.0.0.1:8000> and sign in with `admin` / `admin123`.

**Run the tests:**

```bash
cd app && uv run pytest -q          # 67 tests
```

**Run locally against the real S3 bucket:**

```bash
cd app
AWS_PROFILE=new AWS_REGION=ap-southeast-2 \
STORAGE_BACKEND=s3 \
S3_BUCKET=meditrack-session-notes-808122334310 \
uv run uvicorn meditrack.main:app --port 8000
```

**Provision the three-tier architecture** — note that these have not been run,
and that a NAT Gateway and RDS instance begin incurring charges immediately:

```bash
./infra/10-network.sh          # VPC, subnets, IGW, NAT, routes, S3 endpoint
./infra/20-security-groups.sh  # chained security groups
./infra/30-database.sh         # RDS subnet group and instance (~10 min)
```
