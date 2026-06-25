# Ubiquitous Language

## Claims Processing Lifecycle

| Term | Definition | Aliases to avoid |
| :--- | :--- | :--- |
| **Claim** | A request for reimbursement submitted by a policyholder containing structured facts and an unstructured clinical report. | Ticket, incident, case |
| **Discharge Summary** | The unstructured medical report from the hospital detailing the patient's admission, treatment, ICD-10 diagnosis, and final billing. | Medical report, health record, PDF |
| **Completeness Score** | A ratio (0.0 to 1.0) indicating the fraction of mandatory ACORD fields successfully extracted from the discharge summary. | Extraction rate, fill rate |
| **Cross-Validation** | The process of verifying extracted claim facts against the policy registry (e.g. checking name match, active status). | Policy match, checking registry |
| **Fraud Score** | A hybrid risk score (0.0 to 1.0) computed by combining structured ML classification (60% weight) and LLM narrative inconsistency scan (40% weight). | Risk rate, anomaly index |
| **Coverage Status** | The eligibility determination of the claim peril (COVERED, PARTIAL, EXCLUDED, or NEEDS_REVIEW) against the policy contract. | Insured flag, validation state |
| **Hallucination Guard** | A safety gate that triggers NEEDS_REVIEW with a low confidence exception when the policy retrieval similarity score falls below a threshold. | Prompt shield, retrieval check |
| **Reserve** | The capital set aside for claim settlement, consisting of a point estimate and P10/P50/P90 confidence bands. | Earmarked capital, payout estimate, allocation |
| **Adjuster Route** | The rule-based routing tier (STP_ELIGIBLE, MEDICAL_EXAMINER, STAFF_ADJUSTER, SENIOR_FIELD_ADJUSTER) assigned to the claim. | Handler tier, bucket |

## Entities & Actor Roles

| Term | Definition | Aliases to avoid |
| :--- | :--- | :--- |
| **Policyholder** | The insured individual whose health coverage contract is registered under a policy number. | Customer, client, member, claimant |
| **Network Hospital** | A healthcare facility on the insurance carrier's approved panel for cashless claim processing. | Panel doctor, medical vendor |
| **Adjuster** | The human reviewer responsible for actioning claims routed to the human-in-the-loop queue. | Manager, auditor, assessor |
| **Supervisor** | The orchestration coordinator (built on LangGraph) managing state transitions and data aggregation across agent nodes. | Master, orchestrator, graph |

## Relationships

- A **Policyholder** submits a **Claim** accompanied by a **Discharge Summary**.
- A **Claim** undergoes **Cross-Validation** against the **Policyholder's** registered coverage records.
- The **Supervisor** executes specialized modules to compute the **Completeness Score**, **Fraud Score**, **Coverage Status**, and **Reserve**.
- The **Hallucination Guard** acts as an invariant gate on the **Coverage Status** RAG module.
- An **Adjuster Route** determines which human **Adjuster** queue receives the final aggregated **Claim** decision packet.

## Example Dialogue

> **Dev:** "If the **Completeness Score** is below 0.80, do we still run the XGBoost classifier to compute the **Fraud Score**?"
>
> **Domain expert:** "No. If the **Completeness Score** is low or **Cross-Validation** fails, the **Supervisor** must immediately halt the pipeline and flag the **Claim** as incomplete. We only compute the **Fraud Score** and **Coverage Status** for validated, complete claims."
>
> **Dev:** "And how does the **Hallucination Guard** affect the **Coverage Status**?"
>
> **Domain expert:** "If the similarity score of the retrieved policy chunks is too low, the **Hallucination Guard** overrides the LLM entirely, forcing the **Coverage Status** to `NEEDS_REVIEW` and routing the claim to the `MEDICAL_EXAMINER` **Adjuster Route**."
>
> **Dev:** "Got it. So we don't calculate the **Reserve** if the policy details are missing?"
>
> **Domain expert:** "Actually, we still compute a baseline **Reserve** based on the claimed amount, but we skip LLM severity scaling and flag it for manual adjuster verification."

## Flagged Ambiguities

- **"Claimant" vs. "Policyholder"**: The codebase occasionally uses "claimant_name" and "claimant_name_hash", but they refer to the policyholder's name. We standardise on **Policyholder** to avoid confusion when a claimant is a dependent of the policyholder.
- **"Orchestrator" vs. "Supervisor"**: The codebase uses "Orchestrator" in `07_supervisor_orchestrator.py` but refers to the role as "Supervisor" in the architectural overview. We standardise on **Supervisor** as the canonical name of the graph coordinator.
- **"Adjuster Allocation" vs. "Adjuster Route"**: The codebase uses `adjuster_allocation` to mean both the target assignment value and the routing process. We canonicalise the target assignment as **Adjuster Route** and the process as **Adjuster Allocation**.
