import os
import sys
import json
import importlib
import mlflow

# Ensure config module is in path
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.append(repo_root)

import config.llm_client
importlib.reload(config.llm_client)
from config.llm_client import llm

def agent4_reserve(claim_state: dict) -> dict:
    claim_id = claim_state.get("claim_id")
    print(f"[Agent 4] Processing reserve estimation for {claim_id}...")
    
    extracted = claim_state.get("extracted_data", {})
    coverage = claim_state.get("coverage", {})
    
    claimed_amount = extracted.get("claimed_amount", 0)
    if claimed_amount is None: claimed_amount = 0
    try:
        claimed_amount = float(claimed_amount)
    except:
        claimed_amount = 0

    import pandas as pd
    
    diagnosis = extracted.get("diagnosis_icd", "UNKNOWN")
    
    # Base reserve fallback (since local .pkl files were securely purged in Phase 0)
    base_reserve = claimed_amount
    p10_reserve = base_reserve * 0.8
    p90_reserve = base_reserve * 1.2

    if coverage.get("coverage_status") == "PARTIAL":
        base_reserve *= 0.8
        p10_reserve *= 0.8
        p90_reserve *= 0.8
    elif coverage.get("coverage_status") == "EXCLUDED":
        base_reserve = 0
        p10_reserve = 0
        p90_reserve = 0
        
    comparable_claims = []
    try:
        from pyspark.sql import SparkSession
        spark = SparkSession.builder.getOrCreate()
        df_history = spark.table("health_claims_dev.claims.claims_history")
        comps = df_history.filter(df_history.diagnosis_icd == diagnosis).limit(3).collect()
        for c in comps:
            comparable_claims.append({
                "historical_claim_id": c.historical_claim_id,
                "settled_amount": float(c.settled_amount)
            })
    except Exception as e:
        print(f"[Agent 4] Could not fetch comparable claims: {e}")
        
    diagnosis = extracted.get("diagnosis_icd", "UNKNOWN")
    prompt = f"""
    You are an AI Reserve Estimation Agent. Assess the severity of this medical diagnosis and recommend an uplift multiplier (1.0 to 1.5).
    Diagnosis: {diagnosis}
    
    Return a JSON object with:
    - uplift_multiplier (float)
    - reasoning (string)
    Do NOT output anything except valid JSON.
    """
    
    response_text = llm.generate(prompt, max_tokens=200)
    uplift = 1.0
    reasoning = "Standard reserve applied."
    
    try:
        start_idx = response_text.find("{")
        end_idx = response_text.rfind("}") + 1
        if start_idx != -1 and end_idx != -1:
            data = json.loads(response_text[start_idx:end_idx])
            uplift = float(data.get("uplift_multiplier", 1.0))
            reasoning = data.get("reasoning", reasoning)
    except Exception as e:
        print(f"[Agent 4] JSON parse error: {e}")

    final_reserve = base_reserve * uplift
    
    result = {
        "reserve": {
            "initial_reserve_amount": round(final_reserve, 2),
            "confidence_interval": {
                "P10": round(p10_reserve * uplift, 2),
                "P50": round(final_reserve, 2),
                "P90": round(p90_reserve * uplift, 2)
            },
            "reasoning": reasoning,
            "comparable_claims_cited": comparable_claims
        }
    }
    
    try:
        mlflow.log_metric(f"{claim_id}_base_reserve", base_reserve)
        mlflow.log_metric(f"{claim_id}_llm_uplift", uplift)
        mlflow.log_metric(f"{claim_id}_final_reserve", final_reserve)
    except Exception as e:
        print(f"[Agent 4] MLflow log error: {e}")
        
    claim_state.update(result)
    return claim_state
