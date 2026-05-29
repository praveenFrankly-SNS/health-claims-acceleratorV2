# Databricks notebook source
# MAGIC %md
# MAGIC # 08 Adjuster Allocation
# MAGIC Deterministic rule-based function to route claims to the correct adjuster tier.

# COMMAND ----------

pip install pyyaml

# COMMAND ----------

# Automatically restart Python to ensure typing_extensions updates are loaded cleanly
try:
    dbutils.library.restartPython()
except Exception:
    pass

# COMMAND ----------

def allocate_adjuster(claim_state: dict) -> dict:
    """
    Rule-based routing logic. No LLM involved.
    """
    fraud_score = claim_state.get("fraud", {}).get("fraud_score", 0)
    reserve_amount = claim_state.get("reserve", {}).get("initial_reserve_amount", 0)
    coverage_status = claim_state.get("coverage", {}).get("coverage_status", "NEEDS_REVIEW")
    
    print(f"[Adjuster Allocation] Routing claim {claim_state.get('claim_id')}")
    
    # Read from config/thresholds.yml
    import yaml
    import os
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
    
    claim_state.update(result)
    return claim_state

# COMMAND ----------

if __name__ == "__main__":
    test_state = {"fraud": {"fraud_score": 0.8}, "reserve": {"initial_reserve_amount": 100000}}
    res = allocate_adjuster(test_state)
    print(res["adjuster_allocation"])