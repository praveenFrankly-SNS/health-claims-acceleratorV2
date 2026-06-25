"""
Test Censoring Bias Safety in Physician Fraud Ratio.

Asserts that a physician with claims in INVESTIGATION_PENDING status has those
claims excluded from both numerator AND denominator of physician_fraud_ratio.
This prevents the censoring-bias bug where open investigations are silently
treated as "not fraud", inflating the denominator and deflating the ratio.
"""
import os
import sys
import csv
import pytest
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def load_csv(filename: str) -> list[dict]:
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "structured")
    path = os.path.join(data_dir, filename)
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


class TestCensoringBias:
    """Verify that INVESTIGATION_PENDING claims are handled correctly in fraud ratio."""

    @pytest.fixture(autouse=True)
    def load_data(self):
        self.claims = load_csv("claim_submissions.csv")
        self.providers = load_csv("provider_registry.csv")
        self.clinical = load_csv("clinical_records.csv")

    def test_investigation_pending_claims_exist(self):
        """Verify the generator produces INVESTIGATION_PENDING claims."""
        pending = [c for c in self.claims if c["status"] == "INVESTIGATION_PENDING"]
        assert len(pending) > 0, (
            "No INVESTIGATION_PENDING claims found — generator should produce some "
            "for censoring-bias testing"
        )

    def test_fraud_ratio_excludes_pending_from_denominator(self):
        """
        Recompute physician_fraud_ratio from raw data and verify that
        INVESTIGATION_PENDING claims are excluded from both numerator
        and denominator. Then compare against the stored ratio.
        """
        # Map claim_id -> physician_registration_number
        claim_to_physician = {}
        for rec in self.clinical:
            if rec["claim_id"] not in claim_to_physician:
                claim_to_physician[rec["claim_id"]] = rec["attending_physician_registration_number"]

        # Group claim statuses by physician
        physician_statuses = defaultdict(list)
        for claim in self.claims:
            physician = claim_to_physician.get(claim["claim_id"])
            if physician:
                physician_statuses[physician].append(claim["status"])

        # Compute expected ratio (excluding INVESTIGATION_PENDING)
        for physician_reg, statuses in physician_statuses.items():
            resolved = [s for s in statuses if s != "INVESTIGATION_PENDING"]
            pending = [s for s in statuses if s == "INVESTIGATION_PENDING"]

            if not resolved:
                expected_ratio = 0.0
            else:
                fraud_count = sum(1 for s in resolved if s == "RESOLVED_FRAUD")
                expected_ratio = fraud_count / len(resolved)

            # Find stored ratio in provider_registry
            stored = [p for p in self.providers
                      if p["physician_registration_number"] == physician_reg]
            if not stored:
                continue

            stored_ratio = float(stored[0]["historical_fraud_flag_ratio"])

            # Compare with tolerance
            assert abs(stored_ratio - expected_ratio) < 0.001, (
                f"Physician {physician_reg}: stored ratio {stored_ratio} != "
                f"expected {expected_ratio:.4f} (pending={len(pending)}, resolved={len(resolved)})"
            )

    def test_pending_not_counted_as_clean(self):
        """
        Explicit negative test: verify that if we incorrectly included
        INVESTIGATION_PENDING as 'not fraud' in the denominator, the ratio
        would be different (lower) for any physician with pending claims.
        """
        claim_to_physician = {}
        for rec in self.clinical:
            if rec["claim_id"] not in claim_to_physician:
                claim_to_physician[rec["claim_id"]] = rec["attending_physician_registration_number"]

        physician_statuses = defaultdict(list)
        for claim in self.claims:
            physician = claim_to_physician.get(claim["claim_id"])
            if physician:
                physician_statuses[physician].append(claim["status"])

        physicians_with_pending_and_fraud = []
        for physician_reg, statuses in physician_statuses.items():
            has_pending = any(s == "INVESTIGATION_PENDING" for s in statuses)
            has_fraud = any(s == "RESOLVED_FRAUD" for s in statuses)
            if has_pending and has_fraud:
                physicians_with_pending_and_fraud.append(physician_reg)

        if not physicians_with_pending_and_fraud:
            pytest.skip("No physicians have both INVESTIGATION_PENDING and RESOLVED_FRAUD claims")

        for physician_reg in physicians_with_pending_and_fraud:
            statuses = physician_statuses[physician_reg]
            resolved = [s for s in statuses if s != "INVESTIGATION_PENDING"]
            all_statuses = statuses  # Includes pending

            fraud_count = sum(1 for s in resolved if s == "RESOLVED_FRAUD")
            correct_ratio = fraud_count / len(resolved) if resolved else 0
            buggy_ratio = fraud_count / len(all_statuses) if all_statuses else 0

            # The buggy ratio should be strictly less (diluted by pending in denom)
            assert buggy_ratio < correct_ratio or fraud_count == 0, (
                f"Physician {physician_reg}: buggy ratio {buggy_ratio} should be < "
                f"correct ratio {correct_ratio} when pending claims exist"
            )

    def test_claim_status_values(self):
        """Verify all claim statuses are from the expected controlled vocabulary."""
        expected_statuses = {"NEW", "INVESTIGATION_PENDING", "RESOLVED_FRAUD", "RESOLVED_CLEAN"}
        actual_statuses = {c["status"] for c in self.claims}
        unexpected = actual_statuses - expected_statuses
        assert len(unexpected) == 0, (
            f"Unexpected claim statuses found: {unexpected}"
        )
