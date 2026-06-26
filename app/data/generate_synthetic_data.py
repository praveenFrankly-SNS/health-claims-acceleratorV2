"""
Stateful, Chronological Synthetic Data Generator for Health Claims Accelerator v2.

Generates realistic, temporally-ordered health insurance data including:
- Provider registry with physician license numbers and hospital linkage
- Policy lifecycle with FLOATER/INDIVIDUAL types and annual renewals
- Durable member_id across renewal terms with member drift
- Chronological claim events (submissions, pre-auths, clinical records, bills)
- Decoupled fraud labels (noisy logistic function, ~3% base rate)
- Investigation-pending claims for censoring-bias testing
- --generation-as-of-date snapshot parameter

Author: SNS Square | Version: 2.0
"""

import os
import csv
import json
import math
import random
import argparse
from datetime import datetime, timedelta
from typing import Optional

# ---------------------------------------------------------------------------
# Constants & Controlled Vocabularies
# ---------------------------------------------------------------------------

EXPENSE_TYPES = [
    "ROOM_RENT", "PHARMACY", "DIAGNOSTICS",
    "CONSULTANT_FEES", "AMBULANCE", "OTHER"
]

RAW_EXPENSE_LABELS = {
    "ROOM_RENT": ["Room Charges", "Bed Charges", "Accommodation", "Room Rent", "Ward Charges"],
    "PHARMACY": ["Pharmacy", "Medicine", "Drugs", "Medication Charges", "Consumables"],
    "DIAGNOSTICS": ["Lab Tests", "Diagnostics", "Pathology", "Radiology", "X-Ray", "MRI Scan"],
    "CONSULTANT_FEES": ["Doctor Fee", "Surgeon Fee", "Consultant Charges", "Anesthetist Fee", "Specialist Consultation"],
    "AMBULANCE": ["Ambulance", "Emergency Transport", "Ambulance Service"],
    "OTHER": ["Miscellaneous", "Nursing Charges", "ICU Charges", "OT Charges", "Dressing Charges"],
}

DIAGNOSES = [
    {"desc": "Appendectomy", "code": "K35.80", "base_amount": 60000, "category": "SURGICAL"},
    {"desc": "Dengue Fever", "code": "A90", "base_amount": 25000, "category": "MEDICAL"},
    {"desc": "Knee Replacement", "code": "Z96.65", "base_amount": 250000, "category": "SURGICAL"},
    {"desc": "Cataract Surgery", "code": "H25.9", "base_amount": 35000, "category": "SURGICAL"},
    {"desc": "Viral Pneumonia", "code": "J12.9", "base_amount": 50000, "category": "MEDICAL"},
    {"desc": "Coronary Angioplasty", "code": "I25.10", "base_amount": 180000, "category": "SURGICAL"},
    {"desc": "Hernia Repair", "code": "K40.90", "base_amount": 45000, "category": "SURGICAL"},
    {"desc": "Fracture Treatment", "code": "S72.009A", "base_amount": 70000, "category": "SURGICAL"},
    {"desc": "Typhoid Fever", "code": "A01.0", "base_amount": 20000, "category": "MEDICAL"},
    {"desc": "Gallstone Surgery", "code": "K80.20", "base_amount": 55000, "category": "SURGICAL"},
]

PLAN_TIERS = {
    "Silver": {"sum_insured": 300000, "premium": 8000, "dependent_age_limit": 21},
    "Gold":   {"sum_insured": 500000, "premium": 12000, "dependent_age_limit": 25},
    "Premium": {"sum_insured": 1000000, "premium": 25000, "dependent_age_limit": 25},
}

RELATIONSHIPS = ["PRIMARY", "SPOUSE", "CHILD", "FATHER", "MOTHER"]

PHYSICIAN_NAMES = [
    "A. Kumar", "S. Reddy", "P. Singh", "H. Patel", "M. Shah",
    "R. Gupta", "N. Verma", "K. Menon", "L. Rao", "B. Iyer",
    "D. Chatterjee", "V. Nair", "T. Sharma", "J. Banerjee", "C. Joshi",
    "G. Pillai", "F. Das", "E. Mukherjee", "W. Srinivasan", "X. Kapoor",
    "Y. Malhotra", "Z. Hegde", "AA. Bhat", "BB. Kulkarni", "CC. Mishra",
    "DD. Saxena", "EE. Tiwari", "FF. Pandey", "GG. Agarwal", "HH. Choudhury",
    "II. Deshpande", "JJ. Kamath", "KK. Seshadri", "LL. Raghavan", "MM. Sundaram",
    "NN. Venkatesh", "OO. Subramanian", "PP. Raman", "QQ. Narayan", "RR. Bhatt",
    "SS. Arora", "TT. Dhawan", "UU. Khatri", "VV. Bajaj", "WW. Ahuja",
    "XX. Mehra", "YY. Luthra", "ZZ. Sethi", "AB. Kohli", "BC. Tandon",
]

HOSPITALS = [
    {"hospital_id": "HOSP-001", "hospital_name": "Apollo Hospital Coimbatore", "tier": "TIER_1", "network_status": "IN-NETWORK"},
    {"hospital_id": "HOSP-002", "hospital_name": "Fortis Healthcare Mumbai", "tier": "TIER_1", "network_status": "IN-NETWORK"},
    {"hospital_id": "HOSP-003", "hospital_name": "Max Super Speciality Delhi", "tier": "TIER_1", "network_status": "OUT-OF-NETWORK"},
    {"hospital_id": "HOSP-004", "hospital_name": "AIIMS New Delhi", "tier": "GOVT", "network_status": "IN-NETWORK"},
    {"hospital_id": "HOSP-005", "hospital_name": "Manipal Hospital Bangalore", "tier": "TIER_1", "network_status": "IN-NETWORK"},
    {"hospital_id": "HOSP-006", "hospital_name": "City Clinic Chennai", "tier": "TIER_2", "network_status": "OUT-OF-NETWORK"},
    {"hospital_id": "HOSP-007", "hospital_name": "Medanta The Medicity Gurgaon", "tier": "TIER_1", "network_status": "IN-NETWORK"},
    {"hospital_id": "HOSP-008", "hospital_name": "Narayana Health Bangalore", "tier": "TIER_1", "network_status": "IN-NETWORK"},
    {"hospital_id": "HOSP-009", "hospital_name": "Ruby Hall Clinic Pune", "tier": "TIER_2", "network_status": "IN-NETWORK"},
    {"hospital_id": "HOSP-010", "hospital_name": "Government General Hospital Chennai", "tier": "GOVT", "network_status": "IN-NETWORK"},
]

FIRST_NAMES = [
    "Rajan", "Priya", "Amit", "Sunita", "Vijay", "Meena", "Karthik", "Deepa",
    "Rahul", "Anjali", "Suresh", "Kavitha", "Manoj", "Lakshmi", "Arun", "Rekha",
    "Sanjay", "Geeta", "Raj", "Padma", "Ashok", "Nandini", "Ramesh", "Shanti",
    "Vinod", "Sarala", "Ganesh", "Usha", "Prasad", "Hema", "Dinesh", "Uma",
    "Harish", "Vidya", "Mohan", "Radha", "Satish", "Sumathi", "Rajesh", "Bhavani",
]

LAST_NAMES = [
    "Subramanian", "Sharma", "Patel", "Reddy", "Iyer", "Gupta", "Nair", "Singh",
    "Kumar", "Menon", "Das", "Banerjee", "Mukherjee", "Pillai", "Rao", "Verma",
    "Shah", "Joshi", "Kulkarni", "Mishra", "Agarwal", "Chatterjee", "Deshpande",
    "Hegde", "Bhat", "Kapoor", "Malhotra", "Saxena", "Tiwari", "Pandey",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _repo_root():
    """Find the repo root relative to wherever this script is run."""
    if os.path.exists("../notebooks") and os.path.exists("../data"):
        return ".."
    elif os.path.exists("./notebooks") and os.path.exists("./data"):
        return "."
    return "."


def _random_date_between(start: datetime, end: datetime) -> datetime:
    delta = (end - start).days
    if delta <= 0:
        return start
    return start + timedelta(days=random.randint(0, delta))


def _generate_name():
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def _generate_child_name(last_name: str):
    child_first = random.choice(FIRST_NAMES)
    return f"{child_first} {last_name}"


def _noisy_fraud_label(signals: dict) -> int:
    """
    Compute fraud label as a noisy logistic function of weak, partially-
    overlapping signals. Returns 1 (fraud) at ~3% base rate, higher when
    multiple signals fire. Crucially, NO single signal deterministically
    sets the label — this is the decoupling fix from Q6 #2.
    """
    # Base log-odds for ~3% fraud rate: log(0.03 / 0.97) ≈ -3.47
    log_odds = -3.47

    # Each signal contributes a weak additive bump to log-odds
    if signals.get("high_velocity", False):
        log_odds += random.uniform(1.0, 2.5)
    if signals.get("early_claim", False):
        log_odds += random.uniform(0.8, 2.0)
    if signals.get("inflated_amount", False):
        log_odds += random.uniform(1.2, 2.8)
    if signals.get("blacklisted_physician", False):
        log_odds += random.uniform(1.5, 3.0)
    if signals.get("missing_pre_auth_on_surgical", False):
        log_odds += random.uniform(0.5, 1.5)
    if signals.get("non_network_hospital", False):
        log_odds += random.uniform(0.3, 1.0)

    # Add noise
    log_odds += random.gauss(0, 0.5)

    # Convert to probability via sigmoid
    prob = 1.0 / (1.0 + math.exp(-log_odds))

    return 1 if random.random() < prob else 0


# ---------------------------------------------------------------------------
# Core Generator
# ---------------------------------------------------------------------------

class HealthClaimsGenerator:
    def __init__(self, generation_as_of_date: Optional[datetime] = None,
                 num_base_policies: int = 80, years_to_simulate: int = 3,
                 claims_per_year: int = 200,
                 max_inference_claims: Optional[int] = None):
        self.as_of_date = generation_as_of_date or datetime.today()
        self.num_base_policies = num_base_policies
        self.years_to_simulate = years_to_simulate
        self.claims_per_year = claims_per_year
        # If set, claim_submissions/pre_auth/clinical_records/claim_bills will be
        # capped to this many claims after generation. policy_master, policy_members,
        # network_hospitals, provider_registry are NOT capped — they are training data.
        self.max_inference_claims = max_inference_claims
        self.repo_root = _repo_root()

        # Output accumulators
        self.network_hospitals = []
        self.provider_registry = []
        self.policy_master_rows = []
        self.policy_members_rows = []
        self.claim_submissions_rows = []
        self.pre_auth_requests_rows = []
        self.clinical_records_rows = []
        self.claim_bills_rows = []

        # Internal state
        self._member_counter = 0
        self._claim_counter = 0
        self._pre_auth_counter = 0
        self._bill_counter = 0

        # Track per-member durable info: member_id -> {name, dob, relationship, last_name}
        self._member_registry = {}
        # Track per-policy-term settled amounts for floater balance
        # key: policy_number -> total settled in that term
        self._policy_settled = {}
        # Track per-member settled amounts for individual balance
        # key: (policy_number, member_id) -> total settled
        self._member_settled = {}
        # Track all claims for velocity computation
        self._all_claims = []  # list of {member_id, policy_number, date_of_loss, status}

    def _next_member_id(self):
        self._member_counter += 1
        return f"MBR-{self._member_counter:05d}"

    def _next_claim_id(self):
        self._claim_counter += 1
        return f"CLM-2026-{self._claim_counter:05d}"

    def _next_pre_auth_id(self):
        self._pre_auth_counter += 1
        return f"PA-{self._pre_auth_counter:05d}"

    def _next_bill_no(self):
        self._bill_counter += 1
        return f"BILL-{self._bill_counter:06d}"

    # ------------------------------------------------------------------
    # Step 1: Seed Providers & Hospitals
    # ------------------------------------------------------------------
    def seed_providers(self):
        self.network_hospitals = list(HOSPITALS)

        for i, name in enumerate(PHYSICIAN_NAMES):
            reg_no = f"MC-{1000 + i}"
            hospital = random.choice(HOSPITALS)
            is_blacklisted = random.random() < 0.04  # ~4% blacklisted
            self.provider_registry.append({
                "physician_registration_number": reg_no,
                "physician_name": f"Dr. {name}",
                "hospital_id": hospital["hospital_id"],
                "blacklist_status": is_blacklisted,
                "historical_claim_count": 0,
                "historical_fraud_flag_ratio": 0.0,
            })

    # ------------------------------------------------------------------
    # Step 2: Seed Policies with Renewal Lifecycle
    # ------------------------------------------------------------------
    def seed_policies(self):
        """
        Creates base policies and simulates annual renewals.
        Each renewal generates a new policy_number but retains durable member_ids.
        Member drift: children age out, new members added at renewal.
        """
        simulation_start = self.as_of_date - timedelta(days=365 * self.years_to_simulate)

        for base_idx in range(self.num_base_policies):
            tier_name = random.choice(list(PLAN_TIERS.keys()))
            tier = PLAN_TIERS[tier_name]
            policy_type = random.choice(["FLOATER", "INDIVIDUAL"])
            last_name = random.choice(LAST_NAMES)

            # Create primary member
            primary_id = self._next_member_id()
            primary_name = f"{random.choice(FIRST_NAMES)} {last_name}"
            primary_dob = self.as_of_date - timedelta(days=random.randint(25 * 365, 60 * 365))
            self._member_registry[primary_id] = {
                "name": primary_name, "dob": primary_dob,
                "relationship": "PRIMARY", "last_name": last_name,
            }

            # Create dependents
            dependents = []
            if random.random() < 0.6:  # 60% have a spouse
                spouse_id = self._next_member_id()
                spouse_name = f"{random.choice(FIRST_NAMES)} {last_name}"
                spouse_dob = primary_dob + timedelta(days=random.randint(-5 * 365, 5 * 365))
                self._member_registry[spouse_id] = {
                    "name": spouse_name, "dob": spouse_dob,
                    "relationship": "SPOUSE", "last_name": last_name,
                }
                dependents.append(spouse_id)

            num_children = random.choices([0, 1, 2, 3], weights=[0.3, 0.3, 0.25, 0.15])[0]
            for _ in range(num_children):
                child_id = self._next_member_id()
                child_name = _generate_child_name(last_name)
                child_age_years = random.randint(1, 24)
                child_dob = self.as_of_date - timedelta(days=child_age_years * 365)
                self._member_registry[child_id] = {
                    "name": child_name, "dob": child_dob,
                    "relationship": "CHILD", "last_name": last_name,
                }
                dependents.append(child_id)

            all_members = [primary_id] + dependents

            # Simulate annual renewals
            current_inception = simulation_start + timedelta(days=random.randint(0, 364))
            policy_form_version = "v1.0"

            for year_idx in range(self.years_to_simulate):
                policy_number = f"POL-HLT-{20000 + base_idx}-T{year_idx + 1}"
                term_start = current_inception + timedelta(days=365 * year_idx)
                term_end = term_start + timedelta(days=364)

                # Update policy form version on renewal
                if year_idx >= 2:
                    policy_form_version = "v2.0"

                # Policy status
                if term_end < self.as_of_date:
                    status = "RENEWED"
                elif term_start <= self.as_of_date <= term_end:
                    status = "ACTIVE"
                else:
                    status = "FUTURE"

                # ~5% of policies lapse at renewal
                if year_idx > 0 and random.random() < 0.05:
                    status = "LAPSED"

                self.policy_master_rows.append({
                    "policy_number": policy_number,
                    "policy_type": policy_type,
                    "total_sum_insured": tier["sum_insured"],
                    "inception_date": term_start.strftime("%Y-%m-%d"),
                    "premium_paid": tier["premium"],
                    "status": status,
                    "policy_form_version": policy_form_version,
                    "plan_tier": tier_name,
                })

                # Enroll members for this term with member drift
                for mid in all_members:
                    info = self._member_registry[mid]
                    age_at_term_start = (term_start - info["dob"]).days // 365

                    # Child ages out past dependent age limit
                    if info["relationship"] == "CHILD" and age_at_term_start > tier["dependent_age_limit"]:
                        continue  # not enrolled this term

                    # Spouse removal (small chance at renewal)
                    if info["relationship"] == "SPOUSE" and year_idx > 0 and random.random() < 0.02:
                        continue

                    # Coverage dates
                    cov_start = term_start
                    # Mid-term additions (newborns, new spouse)
                    if year_idx > 0 and info["relationship"] in ("CHILD", "SPOUSE"):
                        if random.random() < 0.05:  # 5% chance of mid-term addition
                            cov_start = _random_date_between(term_start, term_end)
                    cov_end = term_end

                    self.policy_members_rows.append({
                        "policy_number": policy_number,
                        "member_id": mid,
                        "member_name": info["name"],
                        "relationship_to_primary": info["relationship"],
                        "date_of_birth": info["dob"].strftime("%Y-%m-%d"),
                        "coverage_start_date": cov_start.strftime("%Y-%m-%d"),
                        "coverage_end_date": cov_end.strftime("%Y-%m-%d"),
                    })

                # Add newborns at renewal
                if year_idx > 0 and random.random() < 0.03:
                    newborn_id = self._next_member_id()
                    newborn_name = _generate_child_name(last_name)
                    newborn_dob = _random_date_between(term_start, term_end)
                    self._member_registry[newborn_id] = {
                        "name": newborn_name, "dob": newborn_dob,
                        "relationship": "CHILD", "last_name": last_name,
                    }
                    all_members.append(newborn_id)
                    self.policy_members_rows.append({
                        "policy_number": policy_number,
                        "member_id": newborn_id,
                        "member_name": newborn_name,
                        "relationship_to_primary": "CHILD",
                        "date_of_birth": newborn_dob.strftime("%Y-%m-%d"),
                        "coverage_start_date": newborn_dob.strftime("%Y-%m-%d"),
                        "coverage_end_date": term_end.strftime("%Y-%m-%d"),
                    })

    # ------------------------------------------------------------------
    # Step 3: Generate Claims Chronologically
    # ------------------------------------------------------------------
    def generate_claims(self):
        """
        Generates claims across the simulation timeline chronologically.
        Each claim gets: submission, pre-auth (maybe), clinical record(s), bill lines.
        Fraud labels are assigned via a noisy logistic function, decoupled from
        anomaly injection.
        """
        simulation_start = self.as_of_date - timedelta(days=365 * self.years_to_simulate)

        # Build a lookup of active members per policy term
        member_term_lookup = {}  # policy_number -> list of member rows
        for pm in self.policy_members_rows:
            member_term_lookup.setdefault(pm["policy_number"], []).append(pm)

        # Collect active policy terms (non-LAPSED, non-FUTURE)
        active_policies = [
            p for p in self.policy_master_rows
            if p["status"] in ("ACTIVE", "RENEWED")
        ]

        if not active_policies:
            print("Warning: No active policies to generate claims against.")
            return

        total_claims = self.claims_per_year * self.years_to_simulate

        # Generate claim dates spread across the simulation period
        claim_dates = sorted([
            _random_date_between(simulation_start, self.as_of_date)
            for _ in range(total_claims)
        ])

        for claim_date in claim_dates:
            # Find a policy whose term covers this date
            eligible_policies = [
                p for p in active_policies
                if datetime.strptime(p["inception_date"], "%Y-%m-%d") <= claim_date
                   <= datetime.strptime(p["inception_date"], "%Y-%m-%d") + timedelta(days=364)
            ]
            if not eligible_policies:
                continue

            policy = random.choice(eligible_policies)
            policy_number = policy["policy_number"]

            # Find members covered on this date
            members = member_term_lookup.get(policy_number, [])
            covered_members = [
                m for m in members
                if datetime.strptime(m["coverage_start_date"], "%Y-%m-%d") <= claim_date
                   <= datetime.strptime(m["coverage_end_date"], "%Y-%m-%d")
            ]
            if not covered_members:
                continue

            member = random.choice(covered_members)
            member_id = member["member_id"]
            member_info = self._member_registry[member_id]

            diagnosis = random.choice(DIAGNOSES)
            hospital = random.choice(HOSPITALS)
            physician = random.choice(self.provider_registry)

            # Compute amount with variance
            base_amount = diagnosis["base_amount"]
            claimed_amount = int(base_amount * random.uniform(0.7, 1.5))

            # Compute fraud signal flags (independently of label)
            member_age = (claim_date - member_info["dob"]).days // 365
            policy_inception = datetime.strptime(policy["inception_date"], "%Y-%m-%d")
            days_since_inception = (claim_date - policy_inception).days

            # Compute velocity as-of this claim date
            prior_claims = [
                c for c in self._all_claims
                if c["member_id"] == member_id
                   and c["date_of_loss"] < claim_date
                   and (claim_date - c["date_of_loss"]).days <= 90
            ]
            velocity = len(prior_claims)

            signals = {
                "high_velocity": velocity >= 3,
                "early_claim": days_since_inception < 30,
                "inflated_amount": claimed_amount > base_amount * 2.0,
                "blacklisted_physician": physician["blacklist_status"],
                "missing_pre_auth_on_surgical": (
                    diagnosis["category"] == "SURGICAL" and random.random() < 0.15
                ),
                "non_network_hospital": hospital["network_status"] == "OUT-OF-NETWORK",
            }

            # Inject anomalies independently of fraud label
            if random.random() < 0.08:  # 8% of claims have inflated amounts
                claimed_amount = int(base_amount * random.uniform(2.5, 4.0))
                signals["inflated_amount"] = True

            # Noisy fraud label — decoupled from any single signal
            is_fraud = _noisy_fraud_label(signals)

            # Claim status: most resolved, some pending investigation
            days_to_as_of = (self.as_of_date - claim_date).days
            # If the claim is within 60 days of the generation as-of date,
            # it has a high chance of being pending investigation.
            if days_to_as_of <= 60 and random.random() < 0.5:
                claim_status = "INVESTIGATION_PENDING"
            else:
                if is_fraud:
                    if random.random() < 0.3:
                        claim_status = "RESOLVED_FRAUD"
                    elif random.random() < 0.15:
                        claim_status = "INVESTIGATION_PENDING"
                    else:
                        claim_status = "RESOLVED_CLEAN"
                else:
                    if random.random() < 0.05:
                        claim_status = "INVESTIGATION_PENDING"
                    else:
                        claim_status = "RESOLVED_CLEAN"

            claim_id = self._next_claim_id()
            admission_date = claim_date - timedelta(days=random.randint(0, 5))
            discharge_date = admission_date + timedelta(days=random.randint(1, 10))

            # --- Claim Submission ---
            self.claim_submissions_rows.append({
                "claim_id": claim_id,
                "policy_number": policy_number,
                "claimant_id": member_id,
                "date_of_loss": claim_date.strftime("%Y-%m-%d"),
                "claimed_amount": claimed_amount,
                "submission_date": discharge_date.strftime("%Y-%m-%d"),
                "status": claim_status,
                "is_fraud": is_fraud,
            })

            # --- Pre-Auth Request ---
            if diagnosis["category"] == "SURGICAL" and not signals["missing_pre_auth_on_surgical"]:
                pa_status = random.choices(["APPROVED", "DENIED"], weights=[0.85, 0.15])[0]
                pa_requested = claimed_amount
                pa_approved = int(pa_requested * random.uniform(0.7, 1.0)) if pa_status == "APPROVED" else 0
                self.pre_auth_requests_rows.append({
                    "pre_auth_id": self._next_pre_auth_id(),
                    "claim_id": claim_id,
                    "requested_amount": pa_requested,
                    "approved_amount": pa_approved,
                    "status": pa_status,
                    "request_date": (admission_date - timedelta(days=random.randint(2, 7))).strftime("%Y-%m-%d"),
                })

            # --- Clinical Record(s) ---
            num_records = random.choices([1, 2], weights=[0.85, 0.15])[0]
            for seq in range(num_records):
                rec_diagnosis = diagnosis if seq == 0 else random.choice(DIAGNOSES)
                self.clinical_records_rows.append({
                    "claim_id": claim_id,
                    "record_seq": seq + 1,
                    "admission_date": admission_date.strftime("%Y-%m-%d"),
                    "discharge_date": discharge_date.strftime("%Y-%m-%d"),
                    "hospital_id": hospital["hospital_id"],
                    "diagnosis_icd": rec_diagnosis["code"],
                    "attending_physician_registration_number": physician["physician_registration_number"],
                })

            # --- Itemized Bills ---
            self._generate_bills(claim_id, claimed_amount, discharge_date, hospital)

            # --- Track for velocity / balance ---
            self._all_claims.append({
                "claim_id": claim_id,
                "member_id": member_id,
                "policy_number": policy_number,
                "date_of_loss": claim_date,
                "status": claim_status,
                "settled_amount": claimed_amount if claim_status == "RESOLVED_CLEAN" else 0,
            })

            # --- Generate Discharge Summary Text ---
            if self._claim_counter <= 50:
                self._generate_discharge_summary(
                    claim_id, member_info["name"], policy_number,
                    admission_date, discharge_date, hospital,
                    diagnosis, physician, claimed_amount
                )

        # Update provider registry with historical metrics
        self._update_provider_metrics()

    def _generate_bills(self, claim_id: str, total_amount: int,
                        bill_date: datetime, hospital: dict):
        """Generate itemized bill lines summing approximately to total_amount."""
        # Distribute across expense types with realistic weights
        weights = {
            "ROOM_RENT": random.uniform(0.15, 0.30),
            "PHARMACY": random.uniform(0.10, 0.20),
            "DIAGNOSTICS": random.uniform(0.08, 0.15),
            "CONSULTANT_FEES": random.uniform(0.20, 0.35),
            "OTHER": random.uniform(0.05, 0.15),
        }
        # Normalize
        total_weight = sum(weights.values())
        weights = {k: v / total_weight for k, v in weights.items()}

        remaining = total_amount
        for exp_type, pct in weights.items():
            amount = int(total_amount * pct)
            if amount <= 0:
                continue
            remaining -= amount
            raw_label = random.choice(RAW_EXPENSE_LABELS[exp_type])
            self.claim_bills_rows.append({
                "claim_id": claim_id,
                "bill_no": self._next_bill_no(),
                "bill_date": bill_date.strftime("%Y-%m-%d"),
                "raw_expense_label": raw_label,
                "normalized_expense_type": exp_type,
                "amount": amount,
            })

        # Add remainder as AMBULANCE or OTHER
        if remaining > 0:
            if random.random() < 0.3:
                exp_type = "AMBULANCE"
            else:
                exp_type = "OTHER"
            self.claim_bills_rows.append({
                "claim_id": claim_id,
                "bill_no": self._next_bill_no(),
                "bill_date": bill_date.strftime("%Y-%m-%d"),
                "raw_expense_label": random.choice(RAW_EXPENSE_LABELS[exp_type]),
                "normalized_expense_type": exp_type,
                "amount": remaining,
            })

    def _update_provider_metrics(self):
        """Update provider_registry with historical_claim_count and fraud_flag_ratio."""
        physician_claims = {}  # reg_no -> list of claim statuses
        seen_claims = set()
        for cr in self.clinical_records_rows:
            claim_id = cr["claim_id"]
            if claim_id in seen_claims:
                continue
            seen_claims.add(claim_id)
            reg_no = cr["attending_physician_registration_number"]
            # Find the claim's status
            claim_row = next(
                (c for c in self.claim_submissions_rows if c["claim_id"] == claim_id),
                None
            )
            if claim_row:
                physician_claims.setdefault(reg_no, []).append(claim_row["status"])

        for provider in self.provider_registry:
            reg_no = provider["physician_registration_number"]
            statuses = physician_claims.get(reg_no, [])
            # Exclude INVESTIGATION_PENDING from both numerator and denominator
            resolved = [s for s in statuses if s != "INVESTIGATION_PENDING"]
            provider["historical_claim_count"] = len(statuses)
            if resolved:
                fraud_count = sum(1 for s in resolved if s == "RESOLVED_FRAUD")
                provider["historical_fraud_flag_ratio"] = round(fraud_count / len(resolved), 4)
            else:
                provider["historical_fraud_flag_ratio"] = 0.0

    def _generate_discharge_summary(self, claim_id, patient_name, policy_number,
                                     admission_date, discharge_date, hospital,
                                     diagnosis, physician, amount):
        """Generate a text discharge summary for Agent 1 to consume."""
        templates = [
            f"""DISCHARGE SUMMARY
-----------------
Patient Name: {patient_name}
Policy Number: {policy_number}
Admission Date: {admission_date.strftime("%Y-%m-%d")}
Discharge Date: {discharge_date.strftime("%Y-%m-%d")}
Hospital: {hospital['hospital_name']}

Diagnosis: {diagnosis['desc']}
ICD-10 Code: {diagnosis['code']}

Course in the Hospital:
The patient presented with symptoms relating to {diagnosis['desc']}.
Routine investigations were carried out. The patient was managed
conservatively/surgically and responded well to the treatment.

Final Bill Amount: INR {amount}

Attending Physician: {physician['physician_name']} (Reg No: {physician['physician_registration_number']})""",

            f"""HOSPITAL DISCHARGE RECORD
Hospital: {hospital['hospital_name']}
Patient: {patient_name} | Policy: {policy_number}
Admitted: {admission_date.strftime("%Y-%m-%d")} | Discharged: {discharge_date.strftime("%Y-%m-%d")}

Principal Diagnosis: {diagnosis['desc']} ({diagnosis['code']})
Total Charges: {amount}

Physician: {physician['physician_name']}, {physician['physician_registration_number']}""",

            f"""========================================
CLINICAL DISCHARGE REPORT
========================================
Facility: {hospital['hospital_name']}

PATIENT INFORMATION
Name: {patient_name}
Insurance ID: {policy_number}

ENCOUNTER DETAILS
Date of Admission: {admission_date.strftime("%Y-%m-%d")}
Date of Discharge: {discharge_date.strftime("%Y-%m-%d")}

CLINICAL FINDINGS
Diagnosis: {diagnosis['desc']}
ICD Reference: {diagnosis['code']}
The patient was admitted and treated for the above condition.

FINANCIAL
Total Incurred Amount: {amount} INR

Signed: {physician['physician_name']} ({physician['physician_registration_number']})""",
        ]

        summary = random.choice(templates)
        repo_root = self.repo_root
        os.makedirs(f"{repo_root}/data/raw/unstructured", exist_ok=True)
        filepath = f"{repo_root}/data/raw/unstructured/{claim_id}_discharge_summary.txt"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(summary)

    # ------------------------------------------------------------------
    # Step 4: Trim claim-linked tables to max_inference_claims (optional)
    # ------------------------------------------------------------------
    def _trim_to_max_inference_claims(self):
        """
        Caps claim_submissions to max_inference_claims rows (most recent by date_of_loss).
        All linked tables (pre_auth_requests, clinical_records, claim_bills) are also
        trimmed to only the matching claim_ids.
        policy_master, policy_members, network_hospitals, provider_registry are untouched —
        they serve as training/reference data.
        """
        n = self.max_inference_claims
        if not n or len(self.claim_submissions_rows) <= n:
            return

        # Sort by date_of_loss descending — keep the most recent N claims
        sorted_claims = sorted(
            self.claim_submissions_rows,
            key=lambda c: c["date_of_loss"],
            reverse=True
        )
        self.claim_submissions_rows = sorted_claims[:n]
        kept_ids = {c["claim_id"] for c in self.claim_submissions_rows}

        before_pa = len(self.pre_auth_requests_rows)
        before_cr = len(self.clinical_records_rows)
        before_bills = len(self.claim_bills_rows)

        self.pre_auth_requests_rows = [r for r in self.pre_auth_requests_rows if r["claim_id"] in kept_ids]
        self.clinical_records_rows  = [r for r in self.clinical_records_rows  if r["claim_id"] in kept_ids]
        self.claim_bills_rows       = [r for r in self.claim_bills_rows        if r["claim_id"] in kept_ids]

        print(f"\n  [Trim] claim_submissions capped to {n} (most recent)")
        print(f"  [Trim] pre_auth_requests:  {before_pa} → {len(self.pre_auth_requests_rows)}")
        print(f"  [Trim] clinical_records:   {before_cr} → {len(self.clinical_records_rows)}")
        print(f"  [Trim] claim_bills:        {before_bills} → {len(self.claim_bills_rows)}")
        print(f"  [Kept] policy_master/members/hospitals/providers: UNCHANGED (training data)")

    # ------------------------------------------------------------------
    # Step 5: Write All CSVs
    # ------------------------------------------------------------------
    def write_all(self):
        repo_root = self.repo_root
        structured_dir = f"{repo_root}/data/raw/structured"
        training_dir = f"{repo_root}/data/raw/training"
        os.makedirs(structured_dir, exist_ok=True)
        os.makedirs(f"{repo_root}/data/raw/unstructured", exist_ok=True)

        # ----------------------------------------------------------------
        # Write full training snapshot BEFORE trimming.
        # data/raw/training/ = full historical dataset for fraud model.
        # data/raw/structured/ = inference batch (trimmed to max_inference_claims).
        # ----------------------------------------------------------------
        if self.max_inference_claims:
            os.makedirs(training_dir, exist_ok=True)
            self._write_csv(f"{training_dir}/claim_submissions_training.csv", self.claim_submissions_rows)
            self._write_csv(f"{training_dir}/pre_auth_requests_training.csv", self.pre_auth_requests_rows)
            self._write_csv(f"{training_dir}/clinical_records_training.csv", self.clinical_records_rows)
            self._write_csv(f"{training_dir}/claim_bills_training.csv", self.claim_bills_rows)
            fraud_total = sum(1 for c in self.claim_submissions_rows if c["is_fraud"] == 1)
            print(f"\n  [Training snapshot] {len(self.claim_submissions_rows)} claims written to {training_dir}/")
            print(f"  [Training snapshot] Fraud labels: {fraud_total}/{len(self.claim_submissions_rows)} "
                  f"({100*fraud_total/max(len(self.claim_submissions_rows),1):.1f}%)")

        # Trim claim-linked tables if max_inference_claims is set (keeps policy/member data intact)
        self._trim_to_max_inference_claims()

        self._write_csv(f"{structured_dir}/network_hospitals.csv", self.network_hospitals)
        self._write_csv(f"{structured_dir}/provider_registry.csv", self.provider_registry)
        self._write_csv(f"{structured_dir}/policy_master.csv", self.policy_master_rows)
        self._write_csv(f"{structured_dir}/policy_members.csv", self.policy_members_rows)
        self._write_csv(f"{structured_dir}/claim_submissions.csv", self.claim_submissions_rows)
        self._write_csv(f"{structured_dir}/pre_auth_requests.csv", self.pre_auth_requests_rows)
        self._write_csv(f"{structured_dir}/clinical_records.csv", self.clinical_records_rows)
        self._write_csv(f"{structured_dir}/claim_bills.csv", self.claim_bills_rows)

        # Print summary
        print(f"\n{'='*60}")
        print(f"Synthetic Data Generation Complete (as_of={self.as_of_date.strftime('%Y-%m-%d')})")
        print(f"{'='*60}")
        print(f"  Network Hospitals:     {len(self.network_hospitals)}")
        print(f"  Provider Registry:     {len(self.provider_registry)}")
        print(f"  Policy Master (terms): {len(self.policy_master_rows)}")
        print(f"  Policy Members:        {len(self.policy_members_rows)}")
        print(f"  Claim Submissions:     {len(self.claim_submissions_rows)}")
        print(f"  Pre-Auth Requests:     {len(self.pre_auth_requests_rows)}")
        print(f"  Clinical Records:      {len(self.clinical_records_rows)}")
        print(f"  Claim Bills:           {len(self.claim_bills_rows)}")
        fraud_count = sum(1 for c in self.claim_submissions_rows if c["is_fraud"] == 1)
        pending_count = sum(1 for c in self.claim_submissions_rows if c["status"] == "INVESTIGATION_PENDING")
        print(f"\n  Fraud rate:            {fraud_count}/{len(self.claim_submissions_rows)} "
              f"({100*fraud_count/max(len(self.claim_submissions_rows),1):.1f}%)")
        print(f"  Investigation pending: {pending_count}")
        print(f"  Discharge summaries:   {min(self._claim_counter, 50)} text files")

    def _write_csv(self, path, rows):
        if not rows:
            print(f"  Skipping {path} (no rows)")
            return
        with open(path, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        print(f"  Wrote {len(rows)} rows to {path}")


# ---------------------------------------------------------------------------
# Policy Forms (Hybrid: structured metadata JSON + unstructured clauses)
# ---------------------------------------------------------------------------

def generate_policy_forms(repo_root: str):
    """
    Generates hybrid policy forms: structured JSON metadata + unstructured
    clause text files. Each plan tier gets versioned forms.
    """
    forms_dir = f"{repo_root}/data/policy_forms"
    os.makedirs(forms_dir, exist_ok=True)

    policy_forms = {
        "Silver": {
            "v1.0": {
                "metadata": {
                    "plan_tier": "Silver",
                    "form_version": "v1.0",
                    "effective_start_date": "2023-01-01",
                    "effective_end_date": "2024-12-31",
                    "room_rent_cap_pct": 0.01,
                    "icu_cap_pct": 0.02,
                    "proportionate_deduction_applies": True,
                    "proportionate_deduction_cascades_to": [
                        "CONSULTANT_FEES", "PHARMACY", "DIAGNOSTICS", "OTHER"
                    ],
                    "network_copay": 0.0,
                    "non_network_copay": 0.10,
                    "senior_citizen_copay": 0.20,
                    "senior_citizen_age_threshold": 60,
                    "respiratory_copay": 0.10,
                    "cardiovascular_copay": 0.10,
                    "pre_existing_disease_waiting_months": 48,
                    "specific_disease_waiting_months": 24,
                    "specific_disease_waiting_conditions": ["H25.9", "K40.90", "Z96.65", "K80.20"],
                    "sub_limits": [
                        {"category": "CATARACT", "icd_codes": ["H25.9"], "cap_type": "FIXED", "value": 30000},
                        {"category": "CARDIOVASCULAR", "icd_codes": ["I25.10"], "cap_type": "PCT_SUM_INSURED", "value": 0.50},
                        {"category": "KNEE_REPLACEMENT", "icd_codes": ["Z96.65"], "cap_type": "FIXED", "value": 150000},
                    ],
                    "dependent_age_limit": 21,
                },
            },
            "v2.0": {
                "metadata": {
                    "plan_tier": "Silver",
                    "form_version": "v2.0",
                    "effective_start_date": "2025-01-01",
                    "effective_end_date": "2026-12-31",
                    "room_rent_cap_pct": 0.01,
                    "icu_cap_pct": 0.02,
                    "proportionate_deduction_applies": True,
                    "proportionate_deduction_cascades_to": [
                        "CONSULTANT_FEES", "PHARMACY", "DIAGNOSTICS", "OTHER"
                    ],
                    "network_copay": 0.0,
                    "non_network_copay": 0.10,
                    "senior_citizen_copay": 0.20,
                    "senior_citizen_age_threshold": 60,
                    "respiratory_copay": 0.10,
                    "cardiovascular_copay": 0.10,
                    "pre_existing_disease_waiting_months": 36,
                    "specific_disease_waiting_months": 24,
                    "specific_disease_waiting_conditions": ["H25.9", "K40.90", "Z96.65", "K80.20"],
                    "sub_limits": [
                        {"category": "CATARACT", "icd_codes": ["H25.9"], "cap_type": "FIXED", "value": 40000},
                        {"category": "CARDIOVASCULAR", "icd_codes": ["I25.10"], "cap_type": "PCT_SUM_INSURED", "value": 0.50},
                        {"category": "KNEE_REPLACEMENT", "icd_codes": ["Z96.65"], "cap_type": "FIXED", "value": 175000},
                    ],
                    "dependent_age_limit": 21,
                },
            },
        },
        "Gold": {
            "v1.0": {
                "metadata": {
                    "plan_tier": "Gold",
                    "form_version": "v1.0",
                    "effective_start_date": "2023-01-01",
                    "effective_end_date": "2024-12-31",
                    "room_rent_cap_pct": 0.015,
                    "icu_cap_pct": 0.03,
                    "proportionate_deduction_applies": True,
                    "proportionate_deduction_cascades_to": [
                        "CONSULTANT_FEES", "PHARMACY", "DIAGNOSTICS", "OTHER"
                    ],
                    "network_copay": 0.0,
                    "non_network_copay": 0.05,
                    "senior_citizen_copay": 0.15,
                    "senior_citizen_age_threshold": 60,
                    "respiratory_copay": 0.05,
                    "cardiovascular_copay": 0.05,
                    "pre_existing_disease_waiting_months": 36,
                    "specific_disease_waiting_months": 12,
                    "specific_disease_waiting_conditions": ["H25.9", "K40.90"],
                    "sub_limits": [
                        {"category": "CATARACT", "icd_codes": ["H25.9"], "cap_type": "FIXED", "value": 50000},
                        {"category": "CARDIOVASCULAR", "icd_codes": ["I25.10"], "cap_type": "PCT_SUM_INSURED", "value": 0.75},
                        {"category": "KNEE_REPLACEMENT", "icd_codes": ["Z96.65"], "cap_type": "FIXED", "value": 250000},
                    ],
                    "dependent_age_limit": 25,
                },
            },
            "v2.0": {
                "metadata": {
                    "plan_tier": "Gold",
                    "form_version": "v2.0",
                    "effective_start_date": "2025-01-01",
                    "effective_end_date": "2026-12-31",
                    "room_rent_cap_pct": 0.015,
                    "icu_cap_pct": 0.03,
                    "proportionate_deduction_applies": True,
                    "proportionate_deduction_cascades_to": [
                        "CONSULTANT_FEES", "PHARMACY", "DIAGNOSTICS", "OTHER"
                    ],
                    "network_copay": 0.0,
                    "non_network_copay": 0.05,
                    "senior_citizen_copay": 0.15,
                    "senior_citizen_age_threshold": 60,
                    "respiratory_copay": 0.05,
                    "cardiovascular_copay": 0.05,
                    "pre_existing_disease_waiting_months": 36,
                    "specific_disease_waiting_months": 12,
                    "specific_disease_waiting_conditions": ["H25.9", "K40.90"],
                    "sub_limits": [
                        {"category": "CATARACT", "icd_codes": ["H25.9"], "cap_type": "FIXED", "value": 60000},
                        {"category": "CARDIOVASCULAR", "icd_codes": ["I25.10"], "cap_type": "PCT_SUM_INSURED", "value": 0.75},
                        {"category": "KNEE_REPLACEMENT", "icd_codes": ["Z96.65"], "cap_type": "FIXED", "value": 300000},
                    ],
                    "dependent_age_limit": 25,
                },
            },
        },
        "Premium": {
            "v1.0": {
                "metadata": {
                    "plan_tier": "Premium",
                    "form_version": "v1.0",
                    "effective_start_date": "2023-01-01",
                    "effective_end_date": "2024-12-31",
                    "room_rent_cap_pct": None,
                    "icu_cap_pct": None,
                    "proportionate_deduction_applies": False,
                    "proportionate_deduction_cascades_to": [],
                    "network_copay": 0.0,
                    "non_network_copay": 0.0,
                    "senior_citizen_copay": 0.10,
                    "senior_citizen_age_threshold": 65,
                    "respiratory_copay": 0.0,
                    "cardiovascular_copay": 0.0,
                    "pre_existing_disease_waiting_months": 24,
                    "specific_disease_waiting_months": 0,
                    "specific_disease_waiting_conditions": [],
                    "sub_limits": [],
                    "dependent_age_limit": 25,
                },
            },
            "v2.0": {
                "metadata": {
                    "plan_tier": "Premium",
                    "form_version": "v2.0",
                    "effective_start_date": "2025-01-01",
                    "effective_end_date": "2026-12-31",
                    "room_rent_cap_pct": None,
                    "icu_cap_pct": None,
                    "proportionate_deduction_applies": False,
                    "proportionate_deduction_cascades_to": [],
                    "network_copay": 0.0,
                    "non_network_copay": 0.0,
                    "senior_citizen_copay": 0.10,
                    "senior_citizen_age_threshold": 65,
                    "respiratory_copay": 0.0,
                    "cardiovascular_copay": 0.0,
                    "pre_existing_disease_waiting_months": 24,
                    "specific_disease_waiting_months": 0,
                    "specific_disease_waiting_conditions": [],
                    "sub_limits": [],
                    "dependent_age_limit": 25,
                },
            },
        },
    }

    for tier_name, versions in policy_forms.items():
        for version, data in versions.items():
            # Write structured metadata JSON
            json_path = f"{forms_dir}/{tier_name}_{version}_metadata.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data["metadata"], f, indent=2)
            print(f"  Wrote {json_path}")

    # Keep original .txt clause files as-is for Vector Search RAG
    print("  Policy form clause files (.txt) retained for RAG indexing.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Check if we should skip synthetic generation (if using Supabase)
    use_supabase = False
    try:
        import IPython
        ipy = IPython.get_ipython()
        if ipy and "dbutils" in ipy.user_ns:
            dbutils = ipy.user_ns["dbutils"]
            use_supabase = dbutils.widgets.get("use_supabase").lower() == "true"
    except Exception:
        pass

    if use_supabase:
        print("Skipping synthetic data generation task: 'use_supabase' is set to true.")
        import sys
        sys.exit(0)

    parser = argparse.ArgumentParser(description="Generate synthetic health claims data")
    parser.add_argument(
        "--generation-as-of-date",
        type=str,
        default=None,
        help="Snapshot date (YYYY-MM-DD). Defaults to today."
    )
    parser.add_argument("--num-policies", type=int, default=80)
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--claims-per-year", type=int, default=200)
    parser.add_argument(
        "--max-inference-claims",
        type=int,
        default=None,
        help=(
            "Cap claim_submissions/pre_auth/clinical_records/claim_bills to this many rows "
            "(most recent claims kept). policy_master, policy_members, network_hospitals, "
            "provider_registry are NOT capped — they remain as training data. "
            "Use e.g. --max-inference-claims 25 for fast job runs."
        )
    )

    args = parser.parse_args()

    as_of = None
    if args.generation_as_of_date:
        as_of = datetime.strptime(args.generation_as_of_date, "%Y-%m-%d")

    gen = HealthClaimsGenerator(
        generation_as_of_date=as_of,
        num_base_policies=args.num_policies,
        years_to_simulate=args.years,
        claims_per_year=args.claims_per_year,
        max_inference_claims=args.max_inference_claims,
    )

    gen.seed_providers()
    gen.seed_policies()
    gen.generate_claims()
    gen.write_all()
    generate_policy_forms(gen.repo_root)

    print("\nDone.")
