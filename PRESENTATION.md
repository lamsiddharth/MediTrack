# MediTrack — 10-minute video: slide plan and speaking notes

Weighted the way the brief is: **architecture and cloud services are the
substance** (~5 of the 10 minutes), with a short, concrete application demo to
show there is a real workload underneath.

**Total: 10:00.** Rehearse once with a timer — the usual failure is spending
four minutes on the app demo and rushing the architecture, which is the part
being assessed.

| # | Slide | Time | Running |
|---|---|---|---|
| 1 | Title and team | 0:20 | 0:20 |
| 2 | The problem | 0:40 | 1:00 |
| 3 | Objectives | 0:30 | 1:30 |
| 4 | What MediTrack does | 0:40 | 2:10 |
| 5 | **Live demo** | 1:50 | 4:00 |
| 6 | **Architecture overview** | 1:20 | 5:20 |
| 7 | **Public vs private: the key decision** | 1:00 | 6:20 |
| 8 | **How the tiers reach each other** | 1:00 | 7:20 |
| 9 | **Cloud services and why each** | 1:00 | 8:20 |
| 10 | Deployment pipeline (ECR) | 0:40 | 9:00 |
| 11 | Results | 0:30 | 9:30 |
| 12 | Limitations and conclusion | 0:30 | 10:00 |

> **Division of labour.** The brief requires every member to present. A clean
> split: one person takes slides 1–5 (problem and application), one takes 6–8
> (architecture — the biggest share), one takes 9–12 (services, deployment,
> results). Agree handover sentences in advance so the transitions are not
> awkward.

---

## Slide 1 — Title and team · 0:20

**On screen:** MediTrack — Cloud Deployment of a Hospital Management System.
Team names and roles. Region: `ap-southeast-2`.

> "MediTrack is a hospital management system we wrote, deployed on AWS. I'll
> cover the problem and the application, [name] takes the architecture, and
> [name] covers the cloud services and results."

---

## Slide 2 — The problem · 0:40

**On screen:** four bullets, no paragraphs.

- Records not retrievable under time pressure
- No integrity in the schedule — one doctor booked twice, nothing notices
- Clinical history fragmented across documents
- Documents detached from the visit that produced them

> "A small clinic on paper and spreadsheets fails in specific ways. A clinician
> needs an allergy history in seconds. Two receptionists working the same paper
> diary can double-book a doctor and nothing catches it.
>
> But building the application is only half the problem. The other half — and
> the subject of this project — is **where it runs**: who can reach the
> database, where documents live, what happens when a component fails. The data
> is clinical, so the database must be unreachable from the internet by
> construction, not by convention."

---

## Slide 3 — Objectives · 0:30

**On screen:** O1–O9 condensed to five lines.

- Deploy a working application on public cloud
- **Exactly one public entry point**
- Application server and database **beyond reach of the internet**
- Managed database; durable document storage independent of server lifetime
- Least privilege between tiers; reproducible provisioning

> "Note the second and third: one entry point, and nothing else reachable. Most
> of the architecture follows from those two."

---

## Slide 4 — What MediTrack does · 0:40

**On screen:** the five areas, one line each. Keep it tight — the demo does
the real work.

| Patients | MRN allocation, search, full history on one page |
| Doctors | Roster, specialisation, per-doctor fee |
| Appointments | Day view, clash detection, cancel / no-show |
| Consultations | Symptoms, diagnosis, prescription, follow-up |
| Session notes | Progress notes with attached documents |
| Billing | Fee and payment status, outstanding total |

> "Six areas following the path a patient takes. Rather than list features,
> I'll show the three parts that make it behave like a real system."

---

## Slide 5 — Live demo · 1:50

**Screen recording, not slides.** Rehearse this; have the data ready. Sign in
beforehand so you are not typing a password on camera.

**Run this order, and narrate what matters rather than every click:**

1. **Dashboard** (0:20) — "Today's schedule in time order, who's still
   waiting, and ₹1,200 outstanding. This is the landing page for a receptionist."

2. **Patient record — Kavya Reddy** (0:30) — search, open. Point at the
   **allergy banner**:
   > "Penicillin, as a banner — not a field you have to go looking for. It also
   > appears on every consultation page. An allergy note that isn't in front of
   > the clinician when they prescribe isn't a safety control."

   Scroll the medical history: past diagnosis, prescription, follow-up date.

3. **Double-booking** (0:30) — book a patient at 09:00 with a doctor, then try
   another patient with the **same doctor at 09:10**. Show the refusal:
   > "Twenty-minute slots. It names who already holds it. This is the
   > schedule-integrity problem from slide 2, fixed."

   Then book a **different doctor at 09:00** — accepted.

4. **Record a visit → session note with attachment** (0:30) — from a scheduled
   appointment, record the visit, then add a progress note with a PDF.
   > "The note text and the attachment both go to **S3**, not the database. The
   > row holds only a key. And notes can't be edited or deleted — a record you
   > can silently rewrite isn't much of a record."

   Click the attachment to download it.
   > "That download didn't come through our server. The API returned a redirect
   > to a signed, time-limited S3 URL and the browser fetched it straight from
   > S3. The bucket stays private."

**Handover:** "That's the workload. [Name] will explain where it runs."

---

## Slide 6 — Architecture overview · 1:20

**On screen:** the three-tier diagram from `REPORT.md` §4.1. Build it in three
clicks if your tool allows — public, then private, then data.

> "Three tiers, each reachable only from the one in front of it.
>
> **Public subnet:** one EC2 instance running nginx. It serves the React bundle
> — static files — and forwards `/api` to the application tier. It holds no
> application code, no database credentials, no AWS keys.
>
> **Private subnet:** a second EC2 instance running the FastAPI JSON API. No
> public IP.
>
> **Private subnet, data tier:** RDS PostgreSQL, single-AZ in
> `ap-southeast-2a`. Clinical documents go to S3.
>
> Subnets exist in **two** Availability Zones — `2a` and `2b` — but compute and
> the database run in one. That's a deliberate cost decision and I'll be
> straight about it: there is no failover. Losing `2a` loses the service. What
> the empty second zone buys, for nothing, is that the network is already
> addressed for multi-AZ and the RDS subnet group already spans two zones, so
> enabling it later is one flag rather than a redesign."

---

## Slide 7 — Public vs private: the key decision · 1:00

**On screen:** two route tables side by side.

```
PUBLIC subnet route table          PRIVATE subnet route table
  10.20.0.0/16  -> local             10.20.0.0/16  -> local
  0.0.0.0/0     -> IGW               0.0.0.0/0     -> NAT Gateway
                                     s3 prefix     -> S3 Gateway Endpoint
```

> "This is the slide I'd most want you to take away.
>
> The application tier is private **because its route table has no path to an
> Internet Gateway** — not because a firewall rule denies traffic. There is no
> route for an inbound packet to follow. A security-group mistake alone cannot
> expose it; you would have to change the routing table too.
>
> It still needs outbound access for patches, so the private table routes to a
> **NAT Gateway** sitting in the public subnet. NAT translates outbound
> connections only — there is no inbound path and nothing to misconfigure.
>
> **Security groups** then chain the tiers. Each rule references *another
> security group*, not an IP range:
>
> - port 80 from anywhere → frontend
> - port 9000 from **the frontend's security group** → backend
> - port 5432 from **the backend's security group** → RDS
>
> The database accepts connections from exactly one source, identified by group
> membership — so it stays correct when an instance is replaced and gets a new
> address. And there is no port 22 rule anywhere, because administration goes
> through Systems Manager."

---

## Slide 8 — How the tiers reach each other · 1:00

**On screen:** four arrows, labelled. No Route 53 anywhere.

> "We have no DNS — no Route 53, no domain — so addressing is worth spelling
> out.
>
> **Users → frontend:** an **Elastic IP**. It survives stop/start, so the
> published address is stable without DNS.
>
> **Frontend → backend:** the private IP, inside the VPC. Never touches the
> Internet Gateway or NAT. We assign the backend a **fixed private IP at
> launch** — `10.20.11.10` — rather than reading whatever it got, so the
> address is a property of the architecture, not of one instance. A replacement
> needs no proxy reconfiguration.
>
> **Backend → RDS:** the RDS endpoint name, resolved by the **VPC resolver** —
> which is not Route 53 and needs no hosted zone. Using the name rather than an
> IP matters: if Multi-AZ were enabled, failover changes the address behind
> that name.
>
> **Backend → S3:** through an **S3 Gateway Endpoint**. Requests go over the
> AWS network via a route-table entry instead of out through NAT. NAT charges
> per gigabyte and clinical attachments are the largest things we move, so this
> is real money — and it removes NAT as a dependency for storing a document.
>
> One consequence of using React worth naming: the JavaScript runs in the
> **user's browser**, not on our instance. So the browser cannot reach a
> private subnet directly, which is why nginx proxies `/api` rather than the
> API being exposed. Same origin also means no CORS, and the session cookie can
> stay `HttpOnly` — safer than a token in browser storage that any script can
> read."

---

## Slide 9 — Cloud services and why each · 1:00

**On screen:** service, role, one-line justification.

| Service | Role | Why |
|---|---|---|
| **VPC** + subnets, IGW, NAT, route tables | Network isolation | The tiering above |
| **EC2** × 2 | Both compute tiers | Keeps the networking visible; ECS/EKS adds cost and hides it |
| **RDS** PostgreSQL | Managed database | Backups with point-in-time recovery, encryption at rest, one flag to Multi-AZ |
| **S3** | Clinical documents | 11-nines durability; lifetime independent of any server |
| **S3 Gateway Endpoint** | Keep S3 traffic off NAT | Cost and one less dependency |
| **ECR** | Private image registry | The deployed artefact is the tested artefact |
| **Systems Manager** | Administration, config | No inbound SSH; IAM-governed; every command audited |
| **IAM** instance roles | Service access | Short-lived credentials; nothing stored on disk |

> "Two I want to justify properly.
>
> **RDS over PostgreSQL on the instance** — cheaper to self-host at this size,
> genuinely tempting. We chose RDS for three things that are tedious and easy
> to get wrong: automated backups with point-in-time recovery, encryption at
> rest without key handling, and a single flag to Multi-AZ. Losing the database
> is the worst outcome in this system.
>
> **IAM roles, not access keys.** The application needs two S3 actions on one
> prefix — put and get, nothing else, no delete, no listing, no other bucket.
> That policy is attached to an **instance role**, so the SDK gets short-lived
> credentials from the metadata service and **no secret is stored on the
> instance at all**. The session signing key lives in Parameter Store as an
> encrypted value and is read by the instance using the same role."

---

## Slide 10 — Deployment pipeline · 0:40

**On screen:** build → push → pull, three boxes.

```
  developer                    Amazon ECR                   EC2 instance
  docker build      ──push──►  meditrack-api:TAG  ──pull──►  docker compose up
  (api + web)                  meditrack-web:TAG             (by immutable tag)
```

> "Images are built once, pushed to **ECR** with scan-on-push and **immutable
> tags**, and pulled by tag on the instance — which authenticates with its
> instance role, so no registry credential is stored.
>
> Immutable tags rather than `latest` because recreating the instance must not
> silently deploy a different version.
>
> Why a registry rather than building on the host: the deployed artefact is
> then the same bytes that were built and scanned; rollback is pulling the
> previous tag instead of rebuilding; and the runtime host carries no compiler
> or build cache. ECR stores layers in S3, so pulls also go over that gateway
> endpoint rather than NAT."

---

## Slide 11 — Results · 0:30

**On screen:** the numbers only.

- **73 backend tests** passing — auth gate, the clash rule, validation, storage failure handling
- Frontend type-checked (`strict`), bundle **82 kB gzipped**
- S3 verified against the live service: upload, presigned download, bytes match
- Bucket: public access blocked, SSE-S3, versioning on, TLS-only policy

> "Tests cover behaviour, not lines — that cancelling an appointment *releases*
> the slot, that a storage failure mid-write leaves no database row, that a note
> whose object has vanished degrades in place instead of failing the page.
>
> Three bugs are worth a mention because only running it found them: a
> whitespace-only diagnosis passed `min_length=1` validation and would have
> saved a blank clinical record; presigned URLs signed against S3's global
> endpoint got a redirect that invalidated the signature; and an empty file
> input made the API reject every note saved without an attachment."

---

## Slide 12 — Limitations and conclusion · 0:30

**On screen:** be direct. Markers trust a report that states its gaps.

- **No TLS** — plain HTTP. First thing to fix; synthetic data only until then
- **Single AZ** — no failover; remediation is one RDS flag plus a second instance
- **One account, no roles** — a real system separates reception from clinicians and audits reads
- **No monitoring** — health endpoints exist, nothing alerts

> "The design decision I'd defend is the routing one: private by **absence of a
> route**, not by firewall rule — a stronger guarantee, because a
> security-group error alone can't undo it.
>
> The honest gaps: no TLS, so this holds synthetic data only; and a single
> Availability Zone, so there's no failover. The network is already addressed
> for multi-AZ, which makes that a change rather than a rebuild.
>
> Thank you."

---

## Recording notes

- **Record the demo separately** and cut it in. Live demos go wrong on camera.
- **Zoom the browser to ~125%** — small text is unreadable after compression.
- Clear the browser of unrelated tabs and bookmarks.
- **Say the service names out loud** — "Internet Gateway", "NAT Gateway",
  "Gateway Endpoint", "instance role". The brief asks you to demonstrate use of
  cloud services; the marker needs to hear them.
- If you overrun, cut from slides 2 and 4, never from 6–9.
- Do not read these notes verbatim. They are the argument, not a script.
