import os
import yaml
import mlflow

def allocate_adjuster(claim_state: dict) -> dict:
    """
    Rule-based routing logic. No LLM involved.
    
    v2 fix: blacklist_status == True deterministically overrides all other checks
    and hard-routes to SENIOR_FIELD_ADJUSTER, bypassing the blended fraud score
    entirely. This is evaluated FIRST.
    """
    claim_id = claim_state.get("claim_id")
    fraud_data = claim_state.get("fraud", {})
    fraud_score = fraud_data.get("fraud_score", 0)
    blacklist_status = fraud_data.get("blacklist_status", False)
    physician_fraud_ratio = fraud_data.get("physician_fraud_ratio", 0.0)
    reserve_amount = claim_state.get("reserve", {}).get("initial_reserve_amount", 0)
    coverage_status = claim_state.get("coverage", {}).get("coverage_status", "NEEDS_REVIEW")
    
    print(f"[Adjuster Allocation] Routing claim {claim_id}")
    
    # Resolve repo_root from this file's location (works whether in src/ or app/src/)
    _this_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(_this_dir, "../.."))
    thresholds = {}
    try:
        with open(f"{repo_root}/config/thresholds.yml", "r") as f:
            thresholds = yaml.safe_load(f)
    except Exception as e:
        print(f"[Adjuster Allocation] Warning: Could not load thresholds.yml: {e}")
        
    fraud_high = thresholds.get("fraud_score_high_threshold", 0.70)
    reserve_high = thresholds.get("reserve_amount_high_threshold", 500000)
    fraud_stp = thresholds.get("fraud_score_stp_threshold", 0.30)
    reserve_stp = thresholds.get("reserve_amount_stp_threshold", 50000)
    blacklist_routing = thresholds.get("blacklist_override_routing", "SENIOR_FIELD_ADJUSTER")
    
    routing_reason = ""

    # --- DETERMINISTIC OVERRIDE: blacklisted physician ---
    # This is evaluated BEFORE the blended fraud score. A blacklisted physician
    # bypasses the ML/LLM blend entirely because the signal is deterministic
    # and the risk is categorical, not probabilistic.
    if blacklist_status:
        adjuster = blacklist_routing
        routing_reason = "BLACKLISTED_PHYSICIAN_OVERRIDE"
        print(f"[Adjuster Allocation] ⚠ Blacklisted physician — hard-routed to {adjuster}")
    elif fraud_score > fraud_high or reserve_amount > reserve_high:
        adjuster = "SENIOR_FIELD_ADJUSTER"
        routing_reason = f"fraud_score={fraud_score:.2f} > {fraud_high} or reserve={reserve_amount} > {reserve_high}"
    elif coverage_status == "NEEDS_REVIEW":
        adjuster = "MEDICAL_EXAMINER"
        routing_reason = "coverage_status=NEEDS_REVIEW"
    elif fraud_score < fraud_stp and reserve_amount < reserve_stp and coverage_status == "COVERED":
        adjuster = "STP_ELIGIBLE"  # Straight-Through Processing
        routing_reason = "Low risk — eligible for STP"
    else:
        adjuster = "STAFF_ADJUSTER"
        routing_reason = "Default routing"
        
    result = {
        "adjuster_allocation": adjuster,
        "routing_reason": routing_reason,
    }
    
    try:
        mlflow.log_param(f"{claim_id}_adjuster_allocation", adjuster)
        mlflow.log_param(f"{claim_id}_routing_reason", routing_reason)
    except:
        pass
        
    claim_state.update(result)
    return claim_state
