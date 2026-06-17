# Castellan — Product Brief

> **Working name:** Castellan (the keeper of the keys). Change freely.
> **Hackathon:** Band of Agents Hackathon (lablab.ai) · Track 3 — Regulated & High-Stakes Workflows
> **Status:** Concept for review. Build target: Claude Code.
> **Idea 1 of 2** (companion idea: `CONCORD_PRODUCT_BRIEF.md`).

---

## One-liner

Castellan is a multi-agent system where specialist AI agents detect live cloud security misconfigurations and **collaborate on a shared remediation blackboard** — contributing diagnoses, fixes, and dependencies that converge into one vetted plan — which a policy agent **constrains**, a human **approves**, and which executes as a **reversible** action, with every step sealed in a **cryptographically chained, tamper-evident audit trail**. All coordination happens through Band.

## The problem

Cloud security posture tools (CSPM — Wiz, Prisma Cloud, AWS Security Hub) are excellent at *finding* misconfigurations and poor at *fixing* them. In most orgs:

- Scanners produce thousands of findings; humans triage and remediate by hand.
- Mean-time-to-remediate is **days to weeks**, even for critical issues.
- There is **no defensible record** of who decided to change what, when, and why.
- The few auto-remediation tools that exist are rule-based and dumb — no judgment, no awareness of blast radius, and crucially **not reversible and not gated**, which is exactly why security teams refuse to turn them on.

The gap isn't detection. It's **trustworthy action**: remediation that exercises judgment, is reversible, requires human consent for anything consequential, and produces proof.

## The solution

A standing agent "duty room" built around a shared **remediation blackboard**. In one Band room:

1. A **Scanner** agent ingests cloud configuration / CSPM findings and opens a structured **case file** (the blackboard) for each finding.
2. A **Controller** reads the evolving state of the case and **activates the specialist whose expertise the current state calls for** — pulling in the IAM, Network, or Data/Encryption specialist dynamically, never all at once.
3. Activated specialists **contribute to the shared case**: a diagnosis, a proposed reversible fix, a discovered dependency, a rollback plan. They build the solution together rather than competing for it or arguing over it.
4. A **Risk/Policy agent** writes **hard constraints** onto the blackboard (e.g. "no change may grant org-wide `iam:PassRole`"). Any proposal that violates a constraint is marked invalid and the case re-opens for revision.
5. The plan **converges** when no specialist has anything left to add and every Risk constraint is satisfied with a complete fix + rollback.
6. Any **consequential action is gated behind human approval** (the "key"). On approval, it executes against the live cloud account with its rollback registered.
7. Every contribution, constraint, approval, and executed action is recorded by Band and **sealed into a hash-chained audit log** that can be independently verified as intact.

## Why this wins against *this* field

I went through the submitted projects twice. Two things stand out.

**On domain:** the field is overwhelmingly **cost, risk, and compliance — and almost entirely *review*.** Contract redline, financial-crime investigation, vendor risk, compliance auditing, claims adjudication: all look at a problem and produce an opinion. Castellan is the one system that **doesn't just review — it acts**, reversibly, with proof. Sharpest originality contrast available against this field.

**On coordination mechanic:** the field's coordination patterns cluster into two crowded families — **competitive** (Contract-Net auctions, e.g. the strong submission *MUSTER*) and **conflictual** (debate / "put it on trial", e.g. Recourse, PactWarden, Contract Redline War Room). Castellan deliberately uses the **third, uncrowded family: cooperative shared-state coordination (a blackboard).** Specialists converge on a shared plan instead of bidding for work or arguing. This is a named architecture with real pedigree (blackboard systems — Hearsay-II, BB1), so it reads as engineering depth, not a gimmick.

Net: Castellan shares **neither its domain nor its coordination mechanic** with MUSTER or any other strong submission. The originality is owned, not borrowed.

## Business case & scalability

- **Market:** Cloud security posture management is a multi-billion-dollar category. "Auto-remediation you can actually trust" is the part still unsolved.
- **Value, denominated:** Cut MTTR from days to minutes; produce a continuous, defensible audit trail for SOC 2 / ISO 27001 / PCI. One-sentence pitch: *"Remediate critical cloud risk in minutes instead of weeks, reversibly, with an audit trail your auditor will accept."*
- **Scalability:** Horizontal. Every company on AWS/GCP/Azure has this problem. It's a SaaS control plane, not a niche tool, and it scales **by composition** — new misconfiguration classes are handled by adding specialist agents to the blackboard.

## The three depth pillars

What puts Castellan two tiers above a "pipeline of agents." Each is also a deliberate prize hook.

1. **Blackboard coordination architecture.** Cooperative shared-state coordination: specialists read the evolving case and contribute when the state calls for their expertise; a Controller drives activation and detects convergence; the Risk agent posts hard constraints that shape the solution. The Band room *is* the blackboard. → Distinct from both crowded coordination families; maps to **AI/ML API's "model orchestration"** partner prize.
2. **Reversible, human-gated actions on a live system.** Every fix carries a registered rollback; consequential actions require a human key. The difference between "agents that talk" and "agents that operate" — scores highest on Application-of-Technology.
3. **Provable audit chain.** A SHA-256 hash-chained, tamper-evident record layered on Band's transcript — each entry commits to the previous, so the log (and the blackboard's entire evolution) is *verifiably* intact. A genuine differentiator in a security/compliance framing.

## How it maps to the judging criteria

| Criterion | How Castellan scores |
| --- | --- |
| **Application of Technology** | Band is the *actual* coordination layer: the blackboard control loop runs over @mention activation and shared context, specialists are dynamically activated by case state, the Risk-constraint/revision loop is real agent-to-agent coordination, and consequential actions are human-gated. Multiple frameworks + multiple model providers by design. |
| **Presentation** | The demo has a watchable arc: a finding opens a case → the Controller pulls in the Data Specialist → it proposes a fix on the board → the Risk agent posts a constraint that *invalidates it* → the specialist revises to a scoped, reversible fix → the plan converges → human approves → the action *executes* against the live target → the audit chain verifies. Collaboration + consequence + proof in ~90 seconds. (The IAM/PassRole case is the higher-stakes upgrade once the safe path is green.) |
| **Business Value** | Solves a real, expensive, universal enterprise problem with a risk-denominated outcome and a compliance-grade audit trail. |
| **Originality** | The whole field reviews; Castellan acts. Uncontested domain *and* the uncrowded coordination family. |

## Prize-stacking (deliberate)

One build, eligible for the main pool **and** both partner prizes:

- **CrewAI remediation specialists → AI/ML API** for specialist reasoning and remediation planning. → *Best Use of AI/ML API* ($1,000 cash + $1,000 credits).
- **Scanner → Featherless** for intake/parsing (high-volume open-source inference). A meaningful, defensible use, not a token bolt-on. → *Best Use of Featherless AI*.
- **Controller and Risk → Anthropic** for reliable multi-turn orchestration and independent policy review (on different Claude models).
- Coordination, identity, transcript → **Band** (`BANDHACK26` for Pro).

## Scope discipline (for the build)

Build a believable demo of one workflow, not a product:

- One cloud target (**LocalStack** locally — free, no spend, reversible by nature; a sandbox AWS account is the "real" version).
- A few seeded misconfigurations across the three specialties (public S3 bucket, over-permissive IAM role, security group open to `0.0.0.0/0` on a sensitive port).
- One dramatic Risk-constraint-forces-revision moment, captured on camera.
- One human approval click that triggers a real (reversible) action against the live target.

## Open questions for reviewers

Where I specifically want challenge:

1. **Blackboard legibility on video.** Cooperative convergence is less inherently dramatic than a bidding war. Is the case file assembling itself visible enough, or do we need the UI to animate each contribution and constraint?
2. **Live-action target.** LocalStack (safe, free, less flashy) vs. a real sandbox AWS account (convincing, but credential/blast-radius risk). Which carries the demo?
3. **Reversibility guarantees.** Per-action rollbacks (close port → reopen) vs. full snapshot/restore for everything?
4. **Audit-chain scope.** Hash-chain the Band records only, or also externally anchor the chain head for stronger tamper-evidence?
5. **Domain check.** Cloud security remediation vs. an alternative live-action domain (FinOps cost remediation, data-pipeline self-healing). Security gives the sharpest "act vs. review" contrast — challenge it.
