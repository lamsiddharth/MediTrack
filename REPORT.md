# MediTrack — Cloud Deployment of a Hospital Management System

**Project report**

| | |
|---|---|
| **Application** | MediTrack — hospital management system (patients, appointments, clinical records, billing) |
| **Presentation tier** | React 19, TypeScript, Vite, served by nginx |
| **Application tier** | Python 3.13, FastAPI, SQLAlchemy 2.0, JSON API |
| **Cloud provider** | Amazon Web Services |
| **Region** | `ap-southeast-2` — Asia Pacific (Sydney) |
| **Availability Zones** | `ap-southeast-2a` (active), `ap-southeast-2b` (provisioned, idle) |
| **Architecture** | Three tiers: public presentation, private application, private data |

> **Status of this report.** Both tiers are built, tested and running, and the
> S3 object storage tier is provisioned and verified against the live service.
> The VPC, the separate EC2 instances and the RDS instance described in §3 are
> **designed and scripted but not provisioned** — no compute or database
> resources have been created.
>
> §3 describes the **designed** topology, in which the two tiers occupy
> separate subnets. §3.8 describes the **as-deployed** topology, in which they
> are co-located on a single instance as two containers to keep the running
> cost to one machine. The two differ only in where the tiers run, not in how
> they are separated; §3.8 gives the exact difference. §6 reports results only
> for what was actually executed, and no measurement is claimed that was not
> taken.

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

It runs **nginx**, which does two things:

1. **Serves the React application** — a static bundle of HTML, JavaScript and
   CSS produced by Vite. These are files on disk; no application logic runs
   here.
2. **Reverse-proxies `/api/*`** to the application tier on port 9000.

It also acts as the SSH bastion for administrative access to the private tier.

It carries **no application code, no database credentials and no AWS
credentials**. Concentrating public exposure in a component this thin is the
point: if it is compromised, the attacker gains a proxy and a copy of
JavaScript that is public anyway — not the database credentials, not the S3
keys, and not the clinical data.

#### Why the API must be proxied rather than exposed

This is the part of the design a single-page application forces, and it is
worth stating directly because it is easy to get wrong.

React runs **in the user's browser**, not on the presentation instance. So when
the application fetches `/api/patients`, that request originates from the
user's machine, somewhere on the internet. The application tier is in a private
subnet with no route to an Internet Gateway, so **the browser cannot reach it
directly** — and should not be able to.

Proxying resolves this. The browser only ever talks to the presentation tier,
on one origin:

```
browser --> http://<elastic-ip>/              static React bundle   (files on nginx)
browser --> http://<elastic-ip>/api/patients  proxied to 10.20.11.10:9000
```

Two consequences follow, both of which simplify the system:

- **No CORS.** The bundle and the API share an origin, so there are no
  cross-origin preflight requests and no `Access-Control-Allow-*` headers to
  configure. Exposing the API on its own hostname would require all of that.
- **Session cookies work, and are the safer choice.** Because the request is
  same-origin, the `HttpOnly` session cookie is sent automatically. The common
  SPA alternative — a bearer token in `localStorage` — is readable by any
  script on the page, so a single cross-site scripting flaw leaks the session.
  An `HttpOnly` cookie is not readable by scripts at all.

The nginx configuration separates the two concerns and handles SPA routing:

```nginx
location /api/ {
    proxy_pass http://meditrack_api;      # the private application tier
    proxy_redirect off;                   # see note below
}

location / {
    try_files $uri $uri/ /index.html;     # client-side routes
}
```

`try_files … /index.html` matters: `/patients` is a React Router path, not a
file. Without that fallback, refreshing the page on any route but `/` returns
404 from nginx.

`proxy_redirect off` also matters. An attachment download answers `307` with a
presigned S3 URL. That redirect must reach the **browser**, so that S3 serves
the file directly; if nginx followed it, every clinical document would be
proxied through a `t3.micro`.

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

It runs the MediTrack **API** container, published on port 9000 — a FastAPI
application serving JSON over 24 endpoints. It renders no HTML. What makes this
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
   Simple. Brittle: replacing the instance changes the address and the proxy
   must be reconfigured.
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

A clinician opening a patient record involves two distinct exchanges.

**First load — static assets, served entirely by the presentation tier:**

```
browser --> HTTP :80 to Elastic IP --> IGW --> nginx (10.20.1.x)
        <-- index.html, index.js, index.css        (files on disk)
```

The application tier is not involved at all. React then boots in the browser
and begins fetching data.

**Each data request — proxied to the private tier:**

```
browser --> GET /api/patients/4 --> IGW --> nginx (10.20.1.x)
        --> proxy_pass --> private subnet --> API :9000 (10.20.11.10)
            |
            |-- SQL :5432 ------------------> RDS (private, 2a)
            |                                 patient, appointment, billing rows
            '-- HTTPS via S3 Gateway Endpoint -> S3
                                              note text and attachments
        <-- JSON back through nginx
```

**An attachment download deliberately breaks that pattern.** The API answers
`307` with a short-lived presigned S3 URL, and the browser fetches the object
from S3 **directly**:

```
browser --> GET /api/.../attachment --> nginx --> API
        <-- 307 Location: https://<bucket>.s3.ap-southeast-2.amazonaws.com/...
browser --> GET that URL ----------------------> S3   (no AWS credentials in the browser)
```

The bucket stays private throughout — the URL is signed, time-limited, and
grants access to one object. A clinical document therefore never traverses the
application instance or the proxy, which matters when both are `t3.micro`.

---

### 3.8 As-deployed topology: both tiers on one instance

§3.1–3.7 describe the designed topology. **What is actually deployed
co-locates both tiers on a single EC2 instance**, as two containers on a
private Docker bridge network. This is a cost decision: one `t3.micro` instead
of two, and no NAT Gateway, which together account for most of the figure in
§6.5.

The separation is preserved rather than abandoned:

| Property | Designed (two subnets) | As deployed (one instance) |
|---|---|---|
| Presentation tier | EC2 in public subnet | `web` container |
| Application tier | EC2 in private subnet | `api` container |
| Publishes a host port | frontend only, :80 | `web` only, :80 |
| API reachable from internet | no — no IGW route | no — no published port |
| API addressed as | `10.20.11.10:9000` | `api:9000` |
| Isolation enforced by | route table | Docker network namespace |

The boundary is real in both cases. In `docker-compose.yml` the `api` service
has **no `ports:` block at all** — only `expose:` — so it is reachable on the
bridge network by service name and from nowhere else, not even from the host
itself. Port 80 on `web` is the single published port in the stack.

What co-location genuinely costs is worth being straight about:

- **The isolation is weaker.** A container namespace is a softer boundary than
  a routing table in a different subnet. A container escape reaches the host
  and therefore the other tier; a subnet has no route to cross.
- **A single instance failure takes down both tiers**, rather than one.
- **The tiers cannot be scaled or patched independently.**

What makes the gap small is that nothing in either codebase assumes
co-location. The frontend addresses the API by a configurable upstream
(`API_UPSTREAM`), and the API binds a port and reads its configuration from the
environment. Moving `api` to its own instance in a private subnet means
changing `API_UPSTREAM` from `api:9000` to `10.20.11.10:9000` and running the
`infra/` scripts. No application code changes.

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

### 5.1 Application tier — implemented and tested

A JSON API, in `app/meditrack/`.

| Module | Responsibility |
|---|---|
| `models.py` | Six tables: `users`, `patients`, `doctors`, `appointments`, `consultations`, `session_notes` |
| `schemas.py` | Pydantic request and response models — the contract with the client |
| `db.py` | Engine and session handling; SQLite pragmas or PostgreSQL pooling by URL |
| `security.py` | bcrypt hashing, session cookie, login dependency |
| `storage.py` | Object-storage abstraction with `local` and `s3` drivers |
| `seed.py` | Schema creation, login account, demo data |
| `api/` | `auth`, `dashboard`, `patients`, `doctors`, `appointments`, `consultations`, `notes` |

2,082 lines, 24 endpoints. Response schemas are deliberately separate from the SQLAlchemy
models, so renaming a column cannot silently change the shape of a response.

### 5.2 Presentation tier — implemented and tested

A React single-page application, in `frontend/src/`.

| Path | Responsibility |
|---|---|
| `lib/api.ts` | Fetch wrapper; extracts readable messages from FastAPI error bodies |
| `lib/auth.tsx` | Session context; loads `/auth/me` and `/meta` on start |
| `lib/types.ts` | TypeScript mirrors of the API schemas |
| `lib/format.ts` | Date, time and currency formatting |
| `components/` | `Layout` (nav shell) and shared UI primitives |
| `pages/` | 13 route components |

2,375 lines of TypeScript and TSX.

Two details worth noting:

- **Enumerations come from the server.** `GET /api/meta` returns the valid
  sexes, appointment statuses, payment statuses, the slot length and the
  attachment limits. The client renders dropdowns from that rather than
  hard-coding values that could drift out of step with the backend.
- **No `innerHTML` anywhere.** Multi-line clinical text is rendered by
  splitting on newlines into React elements, so stored text cannot inject
  markup. The server-rendered version needed an explicit escaping filter for
  this; React's default escaping removes the whole class of problem.

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

### 5.3 Storage abstraction

Two drivers behind one interface (`storage.py`), selected by
`STORAGE_BACKEND`:

- `local` — a directory on disk. The default, so the application and its whole
  test suite run with no AWS account. Essential for development and CI.
- `s3` — the deployed path.

Nothing above this module knows which is in use. This is what allowed the S3
integration to be tested exhaustively offline against `moto`, and then verified
separately against the real service.

### 5.4 Infrastructure as scripts — written, not executed

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

### 5.5 Container images

Two images, one per tier.

**`api`** — single-stage `python:3.13-slim`. Runs as a non-root user (uid
10001) and declares a `HEALTHCHECK` against `/healthz`.

**`web`** — multi-stage. `node:22-alpine` installs dependencies with `npm ci`
and runs `vite build`; the resulting `dist/` is copied into `nginx:1.27-alpine`
and the Node stage is discarded. The runtime image therefore contains no Node,
no `node_modules` and no build tooling — only static files and nginx.

The frontend build is the one step that could have been a problem on a
`t3.micro`, since JavaScript bundlers are memory-hungry. Measured locally it
is not: **1.66 seconds, producing 267 kB of JavaScript (82 kB gzipped)**. The
application is small enough that the bundler never approaches the memory
ceiling. Dependencies are copied before source so that a source-only change
reuses the `npm ci` layer.

### 5.6 Deployment mechanism

`deploy.sh` sends the source to the instance over SSH, builds the image there,
and replaces the container. Notable properties:

- **No container registry.** Only source crosses the network — a few megabytes,
  rather than the several hundred a pair of built images would be. Deployment is
  not gated on upload bandwidth, and no registry has to be provisioned or paid
  for.
- **Secrets are assembled locally** and written to the instance's `.env` over
  the SSH channel, so credentials never appear in a remote shell's history or
  process list.
- **Verification, not optimism.** It polls `/healthz` *and* confirms the SPA
  shell is served on `/`, then exits non-zero if either fails — rather than
  reporting success because a command returned.
- **Data volumes are never removed**, so replacing containers cannot destroy
  the database.

---

## 6. Results

### 6.1 What was executed and verified

**Backend test suite — 73 tests, all passing.**

```
$ cd app && uv run pytest -q
........................................................................
73 passed in 44.92s
```

Coverage is behavioural rather than incidental:

| Area | Tests verify |
|---|---|
| Authentication | every protected endpoint returns 401 unauthenticated; wrong password rejected; unknown user and wrong password are indistinguishable; login/`me`/logout cycle |
| Metadata | `/meta` exposes the enumerations and limits the client renders from |
| Patients | registration allocates sequential MRNs; future and malformed dates of birth rejected; unknown sex rejected; search matches name, MRN and phone |
| Appointments | booking succeeds; same doctor in the same slot refused with 409; a 10-minute offset still refused as overlapping; a different doctor at the same time allowed; 25 minutes later allowed; **cancelling releases the slot** |
| Consultations | blank diagnosis rejected; negative fee rejected; recording a visit completes its appointment; one consultation per appointment enforced; walk-ins need no booking |
| Storage | local and S3 drivers round-trip; presigned URLs use the regional host; traversal in object keys and filenames neutralised; oversized and disallowed attachment types rejected; an attachment cannot be fetched through a different consultation |
| Failure handling | a storage outage mid-write records no database row; a note whose object has vanished is reported `unavailable` rather than failing the response |

**Frontend — type-checked and built.** `tsc --noEmit` passes with
`strict`, `noUnusedLocals` and `noUnusedParameters` enabled. `vite build`
produces 267 kB of JavaScript (82 kB gzipped) in 1.66 s.

**Both tiers running together, verified through the proxy.** The backend on
:9000 and the frontend on :5173, with `/api` proxied — the same request path
nginx implements in production:

```
GET  /                      200    SPA shell from the presentation tier
GET  /patients              200    client-side route, shell served
GET  /api/auth/me           401    {"detail":"Not signed in"}
POST /api/auth/login        200    session cookie set
GET  /api/auth/me           200    ...and accepted on the next request
GET  /api/dashboard         200
GET  /api/consultations/1   200
```

The session cookie surviving the proxy hop is the specific thing being checked
there: it is what makes same-origin cookie auth viable instead of a token.

**The double-booking rule, through the full stack:**

```
POST /api/appointments  09:00  doctor 1  -> 201
POST /api/appointments  09:10  doctor 1  -> 409
  "That doctor already has Arjun Sharma booked at 09:00 on 20 Dec 2026.
   Slots are 20 minutes long — pick another time."
POST /api/appointments  09:00  doctor 2  -> 201
```

**S3 integration — verified against the live service.** Not mocked:

```
PUT/GET note body          : OK
presigned host             : meditrack-session-notes-808122334310.s3.ap-southeast-2.amazonaws.com
fetch via presigned URL    : OK
content-disposition        : attachment; filename="Lab_Report.pdf"
```

**End-to-end through both tiers into real S3.** A progress note with a PDF
attachment was submitted through the proxied API. Both objects appeared in the
live bucket:

```
session-notes/consultations/1/notes/00ac36cc.../body.txt              44 B
session-notes/consultations/1/notes/00ac36cc.../attachment/xray.pdf   47 B
```

The attachment download then behaved as designed — the API answered `307` to a
**regional** presigned URL, and following it returned bytes identical to the
upload:

```
app responds : 307
redirect to  : https://meditrack-session-notes-808122334310
                 .s3.ap-southeast-2.amazonaws.com/...signed
final        : 200
diff         : downloaded bytes match the upload
```

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
| S3 bucket, IAM policy | **Provisioned and verified against the live service** |
| Application tier (API), 73 tests | **Implemented and verified** |
| Presentation tier (React), typecheck and build | **Implemented and verified** |
| Both tiers running together, proxied | **Verified locally** |
| `docker-compose.yml`, both Dockerfiles | Written, **images not built** — no Docker available in this environment |
| nginx configuration | Written, **not exercised** — the proxy path was verified through Vite's equivalent proxy instead |
| VPC, subnets, IGW, NAT, routes | Scripted, **not provisioned** |
| EC2 instance(s) | Scripted, **not provisioned** |
| RDS instance | Scripted, **not provisioned** |

Two honest gaps in that list. The container images have never been built, so
the Dockerfiles are unproven; and the nginx configuration has never served a
request. The proxy *behaviour* was verified through Vite's dev proxy, which
implements the same path-based forwarding, but that is not the same artefact.

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

Converting the server-rendered interface into a React client and a JSON API
surfaced two more:

4. **`model_validate(obj, update={...})` is not valid Pydantic v2.** `update` is
   a parameter of `model_copy`, not `model_validate`. Fifteen tests failed with
   a `TypeError` at once; the serialisers now construct their nested models
   explicitly, which is clearer than the shortcut was.
5. **A whitespace-only diagnosis passed validation.** `Field(min_length=1)` is
   satisfied by `"   "`, so a consultation could be saved with a blank
   diagnosis — the single most important field in the record. Required text
   fields now strip before checking. This one is worth dwelling on: the
   server-rendered version had `if not diagnosis.strip()` in the route, and
   moving validation into the schema silently dropped the `.strip()`. A
   refactor can lose a check that no test was watching, which is why the test
   asserting a blank diagnosis is rejected now exists.

A sixth problem was environmental: **Cloudflare WARP intercepts outbound SSH**,
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

| Item | Designed (two subnets) | As deployed (one instance) |
|---|---|---|
| EC2 `t3.micro` | 19 (× 2) | 9 (× 1) |
| RDS `db.t4g.micro`, 20 GB gp3, single-AZ | 17 | 17 |
| **NAT Gateway** (hourly + data processing) | **35** | **—** |
| Elastic IPs | 4 (× 2) | 0 (one, attached) |
| S3 storage and requests (low volume) | <1 | <1 |
| EBS root volumes | 3 | 2 |
| **Total** | **≈ 78** | **≈ 28** |

Co-locating the tiers removes roughly two thirds of the cost, and the NAT
Gateway is most of it — there is no private subnet to give egress to. That
saving is the reason for the as-deployed topology in §3.8, and §3.8 states what
it costs in isolation strength.

In the designed topology the NAT Gateway is the largest single line — more than
both compute tiers together. The S3 Gateway Endpoint is therefore not merely a
networking nicety: it removes per-gigabyte NAT processing charges on the largest
objects the system handles. The alternatives for reducing it further — a NAT
*instance* on a `t3.nano`, or putting the application tier in the public subnet
with no inbound rules — trade either self-managed NAT or the isolation property
of §3.3, which is the substance of the design.

---

## 7. Conclusion

### 7.1 What was achieved

A hospital management application was written, tested and run, and a three-tier
AWS architecture was designed and expressed as reproducible provisioning
scripts. Against the objectives of §2:

| | Objective | Outcome |
|---|---|---|
| O1 | Deploy a working application | Both tiers built and verified running together; VPC deployment scripted, not provisioned |
| O2 | One public entry point | **Achieved in both topologies**: one IGW route in the design, one published port as deployed |
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
├── docker-compose.yml         both tiers, one instance (section 3.8)
├── app/                       APPLICATION TIER
│   ├── Dockerfile             single-stage Python image
│   ├── pyproject.toml         pinned dependencies
│   ├── meditrack/
│   │   ├── config.py          environment configuration
│   │   ├── db.py              engine, session, per-dialect tuning
│   │   ├── models.py          six tables
│   │   ├── schemas.py         Pydantic request/response contract
│   │   ├── security.py        bcrypt and session auth
│   │   ├── storage.py         local and S3 object-storage drivers
│   │   ├── seed.py            schema, account, demo data
│   │   ├── main.py            application assembly
│   │   └── api/               seven routers, 24 endpoints
│   └── tests/                 73 tests
└── frontend/                  PRESENTATION TIER
    ├── Dockerfile             node build stage, nginx runtime stage
    ├── nginx/default.conf     static serving, /api proxy, SPA fallback
    ├── package.json           pinned dependencies
    ├── vite.config.ts         build and dev-proxy configuration
    └── src/
        ├── lib/               api client, auth context, types, formatting
        ├── components/        layout and UI primitives
        ├── pages/             13 route components
        └── styles.css         stylesheet
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

**Run locally** — two processes, no AWS account needed.

Terminal 1, the application tier:

```bash
cd app
uv venv && uv pip install -e '.[dev]'
uv run uvicorn meditrack.main:app --reload --port 9000
```

Terminal 2, the presentation tier:

```bash
cd frontend
npm install
npm run dev
```

Open <http://127.0.0.1:5173> and sign in with `admin` / `admin123`. Vite
proxies `/api` to port 9000, which is the same path-based forwarding nginx
performs in the deployed stack, so the session cookie behaves identically.

**Run the tests:**

```bash
cd app      && uv run pytest -q     # 73 tests
cd frontend && npm run typecheck    # strict TypeScript
cd frontend && npm run build        # production bundle
```

**Run locally against the real S3 bucket** — add to terminal 1:

```bash
AWS_PROFILE=new AWS_REGION=ap-southeast-2 \
STORAGE_BACKEND=s3 \
S3_BUCKET=meditrack-session-notes-808122334310 \
uv run uvicorn meditrack.main:app --port 9000
```

**Run both tiers as the deployed stack** (requires Docker):

```bash
echo "SECRET_KEY=$(head -c 32 /dev/urandom | base64 | tr -d '=+/')" > .env
docker compose up -d --build
```

Open <http://127.0.0.1>. Only `web` publishes a port; `api` is reachable only
on the compose network.

**Provision the three-tier architecture** — note that these have not been run,
and that a NAT Gateway and RDS instance begin incurring charges immediately:

```bash
./infra/10-network.sh          # VPC, subnets, IGW, NAT, routes, S3 endpoint
./infra/20-security-groups.sh  # chained security groups
./infra/30-database.sh         # RDS subnet group and instance (~10 min)
```
