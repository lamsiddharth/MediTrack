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
| **Deployment** | Images published to Amazon ECR and pulled by the instance |

> **How to read this report.** §1–§2 state the problem and objectives. **§3
> describes the application briefly** — what it does and how it is shaped —
> because the infrastructure only makes sense once the workload is clear. **§4
> and §5 are the substance of the project**: the three-tier architecture, how
> the tiers reach one another, and why each cloud service was chosen. §6 covers
> implementation and §7 the conclusions.
>
> The availability and cost figures in §4.8 and §4.9 are analysis derived from
> the topology and from published on-demand rates. They are not measurements,
> and no latency, throughput or availability figure in this report is presented
> as observed.
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
| **O1** | Deploy a working hospital management application onto public cloud infrastructure | §3 — the application; §6.1 — how it is built |
| **O2** | Expose exactly one public entry point, and no more | §4.2 — only the presentation tier has a route to an Internet Gateway |
| **O3** | Place the application server and the database beyond reach of the internet | §4.3 — private subnets with no Internet Gateway route; NAT for egress only |
| **O4** | Use a managed relational database rather than a self-administered one | §5.3 — Amazon RDS for PostgreSQL |
| **O5** | Store clinical documents durably and independently of server lifetime | §5.4 — Amazon S3, versioned and encrypted |
| **O6** | Lay out the network so a move to multi-AZ requires no re-addressing | §4.5 — subnets in two AZs from the outset |
| **O7** | Enforce least privilege between tiers and towards AWS services | §4.4, §5.5 — security-group chaining; scoped IAM policy |
| **O8** | Keep the design reproducible rather than hand-built | §6.3 — provisioning as scripts under `infra/` |
| **O9** | Be explicit about what this design does *not* provide | §4.8, §7.2 — single-AZ, no TLS, no failover |

### 2.1 Out of scope

Stated deliberately, because a reader should not assume these were overlooked:

- **DNS.** No Route 53 hosted zone, no registered domain. The system is reached
  by the presentation tier's Elastic IP address. §4.6 explains how the tiers
  address each other without it.
- **Automatic failover.** Subnets exist in two zones; compute and the database
  run in one. §4.8 quantifies the exposure.
- **TLS.** Traffic is plain HTTP. §7.2 treats this as the first thing to fix and
  explains why it was not done here.
- **Horizontal scaling and load balancing.** One instance per tier.

---

## 3. The application

Before the infrastructure, what is actually being deployed.

**MediTrack** is a hospital management system for a small clinic: one place for
patient records, the appointment diary, clinical notes and billing. It was
written for this project rather than taken off the shelf, so that the thing
being deployed is a realistic workload rather than a placeholder.

### 3.1 What it does

Five areas, following the path a patient actually takes through a clinic.

| Area | What a user can do |
|---|---|
| **Patients** | Register a patient with an auto-allocated medical record number (`MRN-00001`); search by name, MRN or phone; see one page with their details, every appointment and full clinical history |
| **Doctors** | Maintain the roster — specialisation, room, and a per-doctor consultation fee |
| **Appointments** | Book a patient with a doctor; browse any day; filter by status; mark cancelled or no-show |
| **Consultations** | Record what happened at a visit: symptoms, diagnosis, prescription, follow-up date |
| **Session notes** | Add progress notes to a visit afterwards, each able to carry a document such as a lab report or scan |
| **Billing** | A fee and payment status per consultation, an unpaid filter, and total outstanding on the dashboard |

The **dashboard** is the landing page: patient and doctor counts, today's
schedule in time order, who is still waiting to be seen, what is coming up, the
most recent records, and money outstanding.

### 3.2 Three decisions that make it behave like a real system

Most of the application is ordinary create-read-update work. Three parts are
not, and they are the parts worth looking at.

**Double-booking is refused, not merely discouraged.** A clinic working from a
paper diary can book one doctor twice at the same time and nothing notices.
Slots here are 20 minutes, and a booking that overlaps an existing one for the
same doctor is rejected with an error naming who already holds the slot:

```
That doctor already has Arjun Sharma booked at 09:00 on 20 Dec 2026.
Slots are 20 minutes long — pick another time.
```

Cancellations and no-shows release the slot, because a cancelled appointment
should not block the diary.

**Allergies follow the patient.** A known allergy is not a field to go looking
for; it is shown as a banner on the patient record *and* on every consultation
page. An allergy note that is not in front of the clinician at the moment of
prescribing is not a safety control.

**Clinical notes cannot be edited or deleted.** Session notes are append-only.
A record that can be silently rewritten is not much of a record, and
append-only is also less code than the alternative.

### 3.3 How a visit flows through it

```
  register patient  ──►  book appointment  ──►  record consultation
   (MRN allocated)        (clash checked)       (marks booking complete)
                                                      │
                                      ┌───────────────┴───────────────┐
                                      ▼                               ▼
                              add session notes                  set payment
                            (text + attachments)              (unpaid/paid/waived)
```

Recording a visit against a booking marks that booking completed
automatically, so the diary cannot drift out of step with what happened. A
walk-in can be recorded with no prior booking at all.

### 3.4 Shape of the system

Two separate applications, which is what makes the tiering in §4 meaningful
rather than notional:

- a **React** single-page application — the user interface, a bundle of static
  files served to the browser;
- a **FastAPI** JSON API over 24 endpoints — all the logic and all the data
  access.

They share no code and communicate only over HTTP. The browser talks to one
origin; `/api/*` is forwarded to the API.

Six tables hold everything:

```
users ──── authors ───► session_notes ───► consultations ◄─── patients
                                              ▲    ▲              │
                                              │    └──────────────┘
                                        appointments ◄─── doctors
```

A patient is registered, booked in with a doctor, and the visit produces a
consultation record. Session notes hang off the consultation; billing lives on
it. Note text and attachments are **not** in the database — only a key
pointing into object storage, for the reasons in §5.3.

### 3.5 Signing in

One account, username and password, a signed session cookie. No roles, no
tokens, no password reset — deliberately minimal, because access control is not
what this project is about. Three things were not simplified away: the password
is hashed with bcrypt, the login error is identical for an unknown user and a
wrong password so the form cannot be used to discover usernames, and the
post-login redirect accepts only relative paths so it cannot be pointed at
another site.

On an empty database the system seeds itself a working clinic — 5 doctors, 10
patients aged 8 to 78 with varied blood groups and allergies, 13 appointments
positioned relative to today including completed, cancelled and no-show, and 4
written-up consultations with one left unpaid so the outstanding total is not
zero. §7.2 lists what a real deployment would need beyond this.

---


## 4. System architecture

### 4.1 Overview

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
  |    |  - no inbound SSH; admin via SSM        |   |
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

### 4.2 Presentation tier — public subnet

One `t3.micro` in `10.20.1.0/24`, AZ `ap-southeast-2a`, with an Elastic IP.

It runs **nginx**, which does two things:

1. **Serves the React application** — a static bundle of HTML, JavaScript and
   CSS produced by Vite. These are files on disk; no application logic runs
   here.
2. **Reverse-proxies `/api/*`** to the application tier on port 9000.

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

### 4.3 Application tier — private subnet

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

### 4.4 Data tier — private subnet

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
| `sg-backend` | 9000 | **`sg-frontend`** | only the proxy may reach the app |
| `sg-database` | 5432 | **`sg-backend`** | only the app may reach the database |

There is deliberately **no inbound rule for port 22 on either tier**.
Administration goes through Systems Manager, as described in §4.6, so no
administrative port is exposed at all.

The database accepts connections from exactly one source, identified by group
membership rather than by address.

### 4.5 Why two Availability Zones with one deployment

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

### 4.6 How the tiers address one another without Route 53

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

**Administrator → either tier.** Through **AWS Systems Manager**, not SSH. The
SSM agent on each instance opens an outbound connection to the SSM endpoints,
and administrative commands and interactive sessions are delivered over that:

```bash
aws ssm start-session --target <instance-id>
```

This is the stronger option, and it is worth being explicit about why:

- **No inbound SSH rule is needed on either tier**, so port 22 can be closed
  everywhere. There is no listening administrative service to find.
- **No SSH key has to be distributed or rotated.** Access is governed by IAM,
  so revoking an administrator is an IAM change rather than a key rollover
  across hosts.
- **Every command is recorded** in SSM command history and can be sent to
  CloudTrail, which matters for a system holding clinical data: there is an
  audit trail of who ran what.

The private tier remains reachable this way even though it has no public
address and no route to an Internet Gateway, because the agent's connection is
outbound.

### 4.7 Request path, end to end

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

### 4.8 Availability assessment

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

### 4.9 Indicative monthly cost

`ap-southeast-2`, on-demand, excluding free-tier credits. Approximate.

| Item | ~USD/month |
|---|---|
| EC2 `t3.micro` × 2 (presentation, application) | 19 |
| RDS `db.t4g.micro`, 20 GB gp3, single-AZ | 17 |
| **NAT Gateway** (hourly + data processing) | **35** |
| Elastic IPs × 2 (one attached, one on the NAT) | 4 |
| ECR storage (two repositories, 10 images retained) | 1 |
| S3 storage and requests (low volume) | <1 |
| EBS root volumes | 3 |
| **Total** | **≈ 79** |

The NAT Gateway is the largest single line — more than both compute tiers
together. The S3 Gateway Endpoint is therefore not merely a
networking nicety: it removes per-gigabyte NAT processing charges on the largest
objects the system handles. The alternatives for reducing it further — a NAT
*instance* on a `t3.nano`, or putting the application tier in the public subnet
with no inbound rules — trade either self-managed NAT or the isolation property
of §4.3, which is the substance of the design.

---

## 5. Cloud services used

| Service | Role | Configuration |
|---|---|---|
| **Amazon VPC** | Network isolation | `10.20.0.0/16`, four subnets across two AZs |
| **Internet Gateway** | Public inbound and outbound | Attached; default route for public subnets only |
| **NAT Gateway** | Private outbound only | In public subnet `2a`, with its own Elastic IP |
| **Route tables** | Separate public and private routing | Public → IGW; private → NAT + S3 endpoint |
| **Security groups** | Stateful per-tier firewalls | Chained by group reference, §4.4 |
| **Amazon EC2** | Both compute tiers | 2 × `t3.micro`, Amazon Linux 2023 |
| **Elastic IP** | Stable public address without DNS | One for the frontend, one for the NAT |
| **Amazon RDS** | Managed PostgreSQL | `db.t4g.micro`, single-AZ, encrypted, 7-day backups |
| **Amazon ECR** | Private image registry | Two repositories, scan-on-push, immutable tags |
| **Amazon S3** | Clinical documents | Private, versioned, SSE-S3, TLS-only policy |
| **AWS Systems Manager** | Instance administration and configuration | Parameter Store for configuration; no inbound SSH required |
| **S3 Gateway VPC Endpoint** | Keep S3 traffic off NAT | Prefix-list route in the private table |
| **AWS IAM** | Least-privilege service access | One user, two S3 actions, one prefix |

### 5.1 Why EC2 and not a container service

ECS or EKS would remove instance management. Both were rejected for this scale:
EKS has a fixed control-plane charge larger than the entire rest of this
deployment, and ECS on Fargate would still require the same VPC, subnets,
routing and security groups — the parts this project is actually about — while
making the compute layer harder to inspect while learning. EC2 keeps the
networking visible, which is the point.

### 5.2 Why RDS and not PostgreSQL on the instance

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

### 5.3 Why S3 for clinical documents

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

### 5.4 Object layout

```
s3://meditrack-session-notes-<account-id>/
  session-notes/
    consultations/<consultation-id>/
      notes/<random-uid>/
        body.txt                  note text
        attachment/<filename>     optional document
```

The per-note component is a random UUID rather than a database id. Keys
therefore do not depend on database sequence values, which keeps the two stores
independent and means an object key cannot be guessed by incrementing a number.

### 5.5 IAM and the credential problem

The application needs exactly two S3 actions on one prefix:

```json
{
  "Effect": "Allow",
  "Action": ["s3:PutObject", "s3:GetObject"],
  "Resource": "arn:aws:s3:::meditrack-session-notes-<account-id>/session-notes/*"
}
```

No delete, no listing, no other prefix, no other bucket, no other service. If
the application tier were compromised, the reachable blast radius is read and
write on that one prefix.

The policy is attached to an **IAM instance role**, not to a user, so **no
secret is stored on the instance at all**. The SDK obtains short-lived
credentials from the instance metadata service and rotates them automatically.
This is in use: the running instance writes to S3 with no access key present
anywhere on its disk.

One implementation detail that is easy to miss. IMDSv2 requires a PUT to
obtain a token, and the response has an IP time-to-live measured in hops. The
default of 1 is enough for a process on the host but **not for a process in a
container**, which is one hop further away across the bridge network. Left at
the default, the application would fail to obtain credentials with an error
that looks like a permissions problem rather than a networking one. The hop
limit is therefore set to 2.

The same role carries `ssm:GetParameter` scoped to `/meditrack/*` and
`kms:Decrypt` conditioned on `kms:ViaService = ssm`, so the instance can read
its own configuration — including the session signing key, held as an encrypted
`SecureString` — without that value ever being passed on a command line or
written into a launch script.

---

## 6. Implementation

### 6.1 Application tier — implemented and tested

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

### 6.2 Presentation tier — implemented and tested

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

### 6.3 Storage abstraction

Two drivers behind one interface (`storage.py`), selected by
`STORAGE_BACKEND`:

- `local` — a directory on disk. The default, so the application and its whole
  test suite run with no AWS account. Essential for development and CI.
- `s3` — the deployed path.

Nothing above this module knows which is in use. This is what allowed the S3
integration to be tested exhaustively offline against `moto`, and then verified
separately against the real service.

### 6.4 Infrastructure as scripts

The architecture of §4 is expressed as scripts rather than described in prose
and built by hand, so that it is reproducible and reviewable:

| File | Creates |
|---|---|
| `00-config.sh` | Shared variables: region, AZs, CIDRs, instance classes |
| `10-network.sh` | VPC, four subnets, IGW, NAT Gateway, route tables, S3 endpoint |
| `20-security-groups.sh` | The three chained security groups of §4.4 |
| `30-database.sh` | DB subnet group across both AZs, single-AZ RDS instance |
| `bootstrap-frontend.sh` | User-data for the presentation tier |
| `bootstrap-backend.sh` | User-data for the application tier |

Each script finds existing resources by `Name` tag and reuses them rather than
creating duplicates, so a run interrupted part way through can simply be
repeated. Resource identifiers are recorded in `infra/state.env` for later
scripts to consume, which is what lets the network, security groups and
database be provisioned as three separate steps.

Shell scripts against the AWS CLI were chosen over CloudFormation or Terraform
deliberately. At this size the declarative tools' advantages — drift detection
and dependency graphs — buy little, while the scripts keep every API call
visible, which was the point of the exercise. For anything larger the trade
reverses, and §7.2 says so.

### 6.5 Container images

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

### 6.6 Deployment pipeline

Images are built once, published to a private registry, and pulled by the
instance. Nothing is compiled on the host at deploy time.

**Amazon ECR** holds both images, one repository each:

```
<account>.dkr.ecr.ap-southeast-2.amazonaws.com/meditrack-api
<account>.dkr.ecr.ap-southeast-2.amazonaws.com/meditrack-web
```

Both repositories are created with **scan-on-push** and **immutable tags**.

The pipeline has three stages:

**1. Build.** Both images are built from the source in this repository and
tagged with an immutable, dated identifier rather than `latest`:

```bash
TAG=$(date -u +%Y%m%d)-$(git rev-parse --short HEAD)
docker build -t "$REGISTRY/meditrack-api:$TAG" ./app
docker build -t "$REGISTRY/meditrack-web:$TAG" ./frontend
```

A floating tag would mean that recreating the instance could silently deploy a
different version of the application, which defeats the reproducibility the
design depends on. An immutable tag also means the registry will reject an
attempt to overwrite a tag that has already been deployed.

**2. Push.**

```bash
aws ecr get-login-password --region ap-southeast-2 \
  | docker login --username AWS --password-stdin "$REGISTRY"
docker push "$REGISTRY/meditrack-api:$TAG"
docker push "$REGISTRY/meditrack-web:$TAG"
```

**3. Pull and run.** The instance authenticates to ECR using **its instance
role** — no registry credential is stored on the host — and brings the new tag
up:

```bash
aws ecr get-login-password --region ap-southeast-2 \
  | docker login --username AWS --password-stdin "$REGISTRY"
IMAGE_TAG=$TAG docker compose pull
IMAGE_TAG=$TAG docker compose up -d
```

Because the images are already built, this stage is a download and a container
restart: seconds rather than minutes, and it needs no build toolchain, no
compiler and no source code on the instance at all.

#### Why a registry rather than building on the instance

Building on the host is possible and initially tempting, since it avoids
provisioning a registry. It was rejected for four reasons:

- **The deployed artefact would not be the tested artefact.** A registry makes
  the image that was built and scanned the same bytes that run in production.
  Building per-host means every instance produces its own image, and an
  upstream base-image change between two builds produces two different
  deployments from identical source.
- **Rollback becomes trivial.** A previous tag is still in the registry, so
  reverting is a `pull` of the old tag rather than a rebuild from an older
  commit.
- **It removes the build toolchain from the runtime host.** A `t3.micro`
  running a production service should not also carry a compiler, a Node
  toolchain and a build cache, both for disk and for attack surface.
- **It is the only approach that scales past one instance.** With a registry,
  adding a second application instance behind a load balancer is a launch; by
  building per-host it is a build on every new machine.

The instance pulls from ECR over the **S3 Gateway Endpoint** already present
for session notes, since ECR stores its layers in S3. Image pulls therefore do
not traverse the NAT Gateway, which both removes per-gigabyte NAT charges on
the largest transfers the system makes and removes the NAT as a dependency for
deployment.

#### Image retention

An ECR lifecycle policy keeps the ten most recent images per repository and
expires the rest, so the registry does not accumulate every build ever made
while still retaining enough history for a rollback.

## 7. Conclusion

### 7.1 What was achieved

A hospital management application was written, tested and run, and a three-tier
AWS architecture was designed and expressed as reproducible provisioning
scripts. Against the objectives of §2:

| | Objective | Outcome |
|---|---|---|
| O1 | Deploy a working application | Application implemented and verified; infrastructure defined as scripts |
| O2 | One public entry point | Achieved: only the public route table has an Internet Gateway route |
| O3 | App and database unreachable from the internet | Achieved in design: private subnets with NAT egress only |
| O4 | Managed database | RDS PostgreSQL specified; application verified compatible |
| O5 | Durable document storage | **Achieved and verified** — S3, private, versioned, encrypted |
| O6 | Multi-AZ-ready addressing | Achieved in design: subnets in both zones, RDS subnet group spanning them |
| O7 | Least privilege | Achieved: instance role scoped to two S3 actions on one prefix; security groups chained by group reference |
| O8 | Reproducible provisioning | Achieved: `infra/` scripts, idempotent |
| O9 | Be explicit about gaps | §4.8, §7.2 |

The central design decision is the one in §4.3: the application tier is private
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
4. **No automated build pipeline.** §6.6 specifies the registry and the
   image-tagging discipline, but the build and push steps are run by hand. They
   belong in CI, triggered on a commit, so that the image carrying a given
   commit is produced once by a process nobody can skip.
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
8. **Provisioning is scripted, not declarative.** The `infra/` scripts are
   idempotent but imperative: they cannot detect drift, and nothing reconciles
   the account back to the definition if a resource is changed by hand. Beyond
   this size that becomes the dominant concern, and the scripts should be
   replaced by CloudFormation or Terraform.

### 7.3 Reflection

Two lessons, one architectural and one methodological.

The architectural one is the subject of §4.7: isolation is stronger when it
comes from the **absence of a route** than from the presence of a rule. A
security group is a statement about what is allowed; a routing table is a
statement about what is *possible*. Getting that distinction right, and being
able to say why the private subnet is safe even if a security group were
misconfigured, was the most valuable thing learned.

The methodological one concerns the defects fixed during implementation. Three
of them — an empty file input rejected with a 422, attachments silently
discarded by a type check that could never match, and presigned URLs rejected
because they were signed against the wrong endpoint — were invisible to
reasoning about the code and surfaced only by exercising it against the real
service. The middle one is the instructive case: it did not fail loudly. Notes
saved successfully with the attachment dropped, and only a test asserting that
the stored object existed caught it. Code that has not been exercised is a
hypothesis, not a result.

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
├── docker-compose.yml         two-tier stack definition for local use
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
S3_BUCKET=meditrack-session-notes-<account-id> \
uv run uvicorn meditrack.main:app --port 9000
```

**Run both tiers as the deployed stack** (requires Docker):

```bash
echo "SECRET_KEY=$(head -c 32 /dev/urandom | base64 | tr -d '=+/')" > .env
docker compose up -d --build
```

Open <http://127.0.0.1>. Only `web` publishes a port; `api` is reachable only
on the compose network.

**Provision the architecture** — note that these have not been run, and that
a NAT Gateway and RDS instance begin incurring charges immediately:

```bash
./infra/10-network.sh          # VPC, subnets, IGW, NAT, routes, S3 endpoint
./infra/20-security-groups.sh  # chained security groups
./infra/30-database.sh         # RDS subnet group and instance (~10 min)
```
