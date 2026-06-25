"""
Test Deterministic Coverage Math.

Asserts co-pay application, room-rent cap detection, and proportionate-deduction
cascading against fixed mock bills — no LLM calls in this test file.
These tests exercise the pure-math path in coverage.py that should never be
routed through an LLM.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.agents.coverage import _compute_deterministic_deductions, _load_policy_form_metadata


class TestDeterministicCoverageMath:
    """Test the deterministic (non-LLM) coverage computation pipeline."""

    def _silver_form(self) -> dict:
        """Load Silver v1.0 form metadata for testing."""
        meta = _load_policy_form_metadata("Silver", "v1.0")
        if not meta:
            # Fallback to inline test fixture
            meta = {
                "room_rent_cap_pct": 0.01,
                "icu_cap_pct": 0.02,
                "proportionate_deduction_applies": True,
                "proportionate_deduction_cascades_to": ["CONSULTANT_FEES", "PHARMACY", "DIAGNOSTICS", "OTHER"],
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
                ],
                "dependent_age_limit": 21,
            }
        return meta

    def test_senior_citizen_copay(self):
        """60+ member should trigger 20% co-pay on Silver plan."""
        extracted = {
            "claimed_amount": 100000,
            "sum_insured": 300000,
            "member_age": 65,
            "diagnosis_icd": "K35.80",  # Non-respiratory, non-cardiovascular
        }
        result = _compute_deterministic_deductions(extracted, [], self._silver_form())
        assert result["copay_pct"] == 0.20, f"Expected 20% copay, got {result['copay_pct']}"
        assert "Senior citizen" in (result["copay_reason"] or "")

    def test_respiratory_copay(self):
        """Respiratory diagnosis (ICD J*) should trigger 10% co-pay on Silver."""
        extracted = {
            "claimed_amount": 50000,
            "sum_insured": 300000,
            "diagnosis_icd": "J12.9",
        }
        result = _compute_deterministic_deductions(extracted, [], self._silver_form())
        assert result["copay_pct"] == 0.10

    def test_non_network_copay(self):
        """Out-of-network hospital should trigger 10% deduction on Silver."""
        extracted = {
            "claimed_amount": 50000,
            "sum_insured": 300000,
            "diagnosis_icd": "K35.80",
            "hospital_network_status": "OUT-OF-NETWORK",
        }
        result = _compute_deterministic_deductions(extracted, [], self._silver_form())
        assert result["copay_pct"] == 0.10

    def test_room_rent_cap_triggers_proportionate_deduction(self):
        """
        When room rent exceeds 1% of sum insured per day, proportionate
        deduction should cascade to all other expense categories.
        Silver: 1% of 300,000 = 3,000/day cap.
        """
        extracted = {
            "claimed_amount": 80000,
            "sum_insured": 300000,
            "diagnosis_icd": "A90",
            "admission_date": "2026-01-01",
            "discharge_date": "2026-01-06",  # 5 days
        }
        # Room rent: 25,000 total = 5,000/day > 3,000/day cap
        bills = [
            {"normalized_expense_type": "ROOM_RENT", "amount": 25000},
            {"normalized_expense_type": "CONSULTANT_FEES", "amount": 30000},
            {"normalized_expense_type": "PHARMACY", "amount": 15000},
        ]
        result = _compute_deterministic_deductions(extracted, bills, self._silver_form())

        assert result["room_rent_excess"] > 0, "Room rent excess should be detected"
        assert result["proportionate_deduction_applied"] is True
        assert result["proportionate_deduction_factor"] < 1.0
        # Factor should be 3000/5000 = 0.6
        assert abs(result["proportionate_deduction_factor"] - 0.6) < 0.01

    def test_room_rent_within_cap_no_deduction(self):
        """Room rent at or below cap should NOT trigger proportionate deduction."""
        extracted = {
            "claimed_amount": 50000,
            "sum_insured": 300000,
            "diagnosis_icd": "A90",
            "admission_date": "2026-01-01",
            "discharge_date": "2026-01-06",  # 5 days
        }
        # Room rent: 10,000 total = 2,000/day < 3,000/day cap
        bills = [
            {"normalized_expense_type": "ROOM_RENT", "amount": 10000},
            {"normalized_expense_type": "CONSULTANT_FEES", "amount": 30000},
        ]
        result = _compute_deterministic_deductions(extracted, bills, self._silver_form())

        assert result["room_rent_excess"] == 0
        assert result["proportionate_deduction_applied"] is False

    def test_sub_limit_cataract_silver(self):
        """Cataract surgery (H25.9) on Silver should be capped at 30,000."""
        extracted = {
            "claimed_amount": 50000,
            "sum_insured": 300000,
            "diagnosis_icd": "H25.9",
        }
        result = _compute_deterministic_deductions(extracted, [], self._silver_form())
        assert result["sub_limit_triggered"] is True
        assert result["sub_limit_cap"] == 30000

    def test_sub_limit_cardiovascular_pct(self):
        """Cardiovascular (I25.10) on Silver should be capped at 50% of sum insured."""
        extracted = {
            "claimed_amount": 200000,
            "sum_insured": 300000,
            "diagnosis_icd": "I25.10",
        }
        result = _compute_deterministic_deductions(extracted, [], self._silver_form())
        assert result["sub_limit_triggered"] is True
        assert result["sub_limit_cap"] == 150000  # 50% of 300,000

    def test_waiting_period_cataract_under_24_months(self):
        """
        Cataract claim within 24 months of member's coverage_start_date
        should trigger waiting period violation.
        """
        extracted = {
            "claimed_amount": 35000,
            "sum_insured": 300000,
            "diagnosis_icd": "H25.9",
            "admission_date": "2024-06-15",
            "member_coverage_start_date": "2024-01-01",  # Only ~5.5 months of coverage
        }
        result = _compute_deterministic_deductions(extracted, [], self._silver_form())
        assert result["waiting_period_violated"] is True
        assert "H25.9" in (result["waiting_period_reason"] or "")

    def test_waiting_period_cataract_after_24_months(self):
        """Cataract claim after 24 months of coverage should NOT trigger waiting period."""
        extracted = {
            "claimed_amount": 35000,
            "sum_insured": 300000,
            "diagnosis_icd": "H25.9",
            "admission_date": "2026-06-15",
            "member_coverage_start_date": "2023-01-01",  # ~42 months of coverage
        }
        result = _compute_deterministic_deductions(extracted, [], self._silver_form())
        assert result["waiting_period_violated"] is False

    def test_no_deductions_for_clean_claim(self):
        """A clean, non-senior, in-network, non-special-condition claim should have 0 deductions."""
        extracted = {
            "claimed_amount": 40000,
            "sum_insured": 300000,
            "diagnosis_icd": "A90",  # Dengue — no sub-limits, no waiting period
            "admission_date": "2026-01-01",
            "discharge_date": "2026-01-04",
        }
        bills = [
            {"normalized_expense_type": "ROOM_RENT", "amount": 6000},  # 2000/day < 3000 cap
            {"normalized_expense_type": "PHARMACY", "amount": 10000},
        ]
        result = _compute_deterministic_deductions(extracted, bills, self._silver_form())
        assert result["copay_pct"] == 0.0
        assert result["room_rent_excess"] == 0
        assert result["waiting_period_violated"] is False
        assert result["sub_limit_triggered"] is False
        assert result["total_deterministic_deduction"] == 0

    def test_premium_plan_no_room_rent_cap(self):
        """Premium plan should have no room rent cap (room_rent_cap_pct = None)."""
        premium_meta = _load_policy_form_metadata("Premium", "v1.0")
        if not premium_meta:
            premium_meta = {"room_rent_cap_pct": None, "proportionate_deduction_applies": False,
                            "sub_limits": [], "specific_disease_waiting_conditions": [],
                            "specific_disease_waiting_months": 0}

        extracted = {
            "claimed_amount": 200000,
            "sum_insured": 1000000,
            "diagnosis_icd": "A90",
            "admission_date": "2026-01-01",
            "discharge_date": "2026-01-06",
        }
        bills = [{"normalized_expense_type": "ROOM_RENT", "amount": 100000}]  # 20,000/day — very high
        result = _compute_deterministic_deductions(extracted, bills, premium_meta)
        assert result["room_rent_excess"] == 0, "Premium plan should have no room rent cap"
