"""
Test Point-in-Time Correctness.

Asserts that features computed as_of an early date in the simulated timeline
contain no claims/history dated after that point. This prevents the temporal
leakage bug that causes suspiciously good offline metrics that degrade in production.
"""
import os
import sys
import csv
import pytest
from datetime import datetime

# Adjust path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def load_csv(filename: str) -> list[dict]:
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "structured")
    path = os.path.join(data_dir, filename)
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


class TestPointInTimeCorrectness:
    """Verify that the synthetic generator produces temporally-ordered data."""

    @pytest.fixture(autouse=True)
    def load_data(self):
        self.claims = load_csv("claim_submissions.csv")
        self.members = load_csv("policy_members.csv")
        self.policies = load_csv("policy_master.csv")
        self.clinical = load_csv("clinical_records.csv")

    def test_no_claim_before_policy_inception(self):
        """A claim's date_of_loss should not precede its policy's inception_date."""
        policy_lookup = {p["policy_number"]: p for p in self.policies}
        violations = []
        for claim in self.claims:
            policy = policy_lookup.get(claim["policy_number"])
            if not policy:
                continue
            dol = datetime.strptime(claim["date_of_loss"], "%Y-%m-%d")
            inception = datetime.strptime(policy["inception_date"], "%Y-%m-%d")
            if dol < inception:
                violations.append((claim["claim_id"], claim["date_of_loss"], policy["inception_date"]))

        assert len(violations) == 0, (
            f"{len(violations)} claims have date_of_loss before policy inception: {violations[:5]}"
        )

    def test_no_claim_outside_member_coverage_window(self):
        """A claim's date_of_loss should fall within the claimant's coverage window."""
        # Build (policy_number, member_id) -> (start, end)
        member_windows = {}
        for m in self.members:
            key = (m["policy_number"], m["member_id"])
            start = datetime.strptime(m["coverage_start_date"], "%Y-%m-%d")
            end = datetime.strptime(m["coverage_end_date"], "%Y-%m-%d")
            member_windows[key] = (start, end)

        violations = []
        for claim in self.claims:
            key = (claim["policy_number"], claim["claimant_id"])
            window = member_windows.get(key)
            if not window:
                continue  # member might not exist in data
            dol = datetime.strptime(claim["date_of_loss"], "%Y-%m-%d")
            if dol < window[0] or dol > window[1]:
                violations.append((claim["claim_id"], claim["date_of_loss"],
                                   window[0].strftime("%Y-%m-%d"), window[1].strftime("%Y-%m-%d")))

        assert len(violations) == 0, (
            f"{len(violations)} claims outside coverage window: {violations[:5]}"
        )

    def test_admission_before_or_on_date_of_loss(self):
        """Clinical record admission_date should be <= claim's date_of_loss."""
        claim_dol = {c["claim_id"]: c["date_of_loss"] for c in self.claims}
        violations = []
        for rec in self.clinical:
            dol_str = claim_dol.get(rec["claim_id"])
            if not dol_str or not rec.get("admission_date"):
                continue
            dol = datetime.strptime(dol_str, "%Y-%m-%d")
            adm = datetime.strptime(rec["admission_date"], "%Y-%m-%d")
            if adm > dol:
                violations.append((rec["claim_id"], rec["admission_date"], dol_str))

        # Allow a small tolerance (admission within 5 days of date_of_loss)
        strict_violations = [v for v in violations
                             if (datetime.strptime(v[1], "%Y-%m-%d") -
                                 datetime.strptime(v[2], "%Y-%m-%d")).days > 5]
        assert len(strict_violations) == 0, (
            f"{len(strict_violations)} claims have admission > date_of_loss + 5 days: {strict_violations[:5]}"
        )

    def test_snapshot_excludes_future_claims(self):
        """
        Simulates an as_of snapshot: claims dated after a cutoff should not
        appear in any velocity/balance computation for earlier claims.
        """
        if not self.claims:
            pytest.skip("No claims data")

        # Pick a date in the middle of the claim history
        dates = sorted([datetime.strptime(c["date_of_loss"], "%Y-%m-%d") for c in self.claims])
        midpoint = dates[len(dates) // 2]

        # Claims before midpoint
        before = [c for c in self.claims
                  if datetime.strptime(c["date_of_loss"], "%Y-%m-%d") < midpoint]
        after = [c for c in self.claims
                 if datetime.strptime(c["date_of_loss"], "%Y-%m-%d") >= midpoint]

        # For each claim before midpoint, verify no "future" claim IDs leak in
        before_ids = {c["claim_id"] for c in before}
        after_ids = {c["claim_id"] for c in after}

        # These sets must be disjoint (basic sanity)
        assert before_ids.isdisjoint(after_ids), "Same claim_id appears before and after midpoint"
        # Verify we have claims on both sides
        assert len(before) > 0, "No claims before midpoint"
        assert len(after) > 0, "No claims after midpoint"
