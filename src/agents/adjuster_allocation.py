import os
import yaml
import mlflow

def allocate_adjuster(claim_state: dict) -> dict:
    """
    Rule-based routing logic. No LLM involved.
    """
    claim_id = claim_state.get("claim_id")
    fraud_score = claim_state.get("fraud", {}).get("fraud_score", 0)
    reserve_amount = claim_state.get("reserve", {}).get("initial_reserve_amount", 0)
    coverage_status = claim_state.get("coverage", {}).get("coverage_status", "NEEDS_REVIEW")
    
    print(f"[Adjuster Allocation] Routing claim {claim_id}")
    
    repo_root = ".." if os.path.exists("../config/thresholds.yml") else "."
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
    
    if fraud_score > fraud_high or reserve_amount > reserve_high:
        adjuster = "SENIOR_FIELD_ADJUSTER"
    elif coverage_status == "NEEDS_REVIEW":
        adjuster = "MEDICAL_EXAMINER"
    elif fraud_score < fraud_stp and reserve_amount < reserve_stp and coverage_status == "COVERED":
        adjuster = "STP_ELIGIBLE"  # Straight-Through Processing
    else:
        adjuster = "STAFF_ADJUSTER"
        
    result = {
        "adjuster_allocation": adjuster
    }
    
    try:
        mlflow.log_param(f"{claim_id}_adjuster_allocation", adjuster)
    except:
        pass
        
    claim_state.update(result)
    return claim_state
