# Databricks notebook source
# MAGIC %md
# MAGIC # 06 Agent 4: Reserve Estimation
# MAGIC Uses regression prototype and LLM severity uplift to set an initial reserve amount.

# COMMAND ----------

# MAGIC %pip install scikit-learn pandas

# COMMAND ----------

import os
import sys
import json

import importlib

notebook_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
sys.path.append(os.path.abspath(os.path.join(notebook_dir, "..")))
import config.llm_client
importlib.reload(config.llm_client)  # Force reload to avoid Databricks caching
from config.llm_client import llm

# Force inject Databricks credentials if running in a Notebook
try:
    ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
    if not llm.workspace_url:
        llm.workspace_url = ctx.apiUrl().get()
    if not llm.databricks_token:
        llm.databricks_token = ctx.apiToken().get()
except Exception:
    pass

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
    
    # 1. Base reserve estimation
    diagnosis = extracted.get("diagnosis_icd", "UNKNOWN")
    
    # Fallback arithmetic reserve (since local .pkl files were securely purged in Phase 0)
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
        
    # 2. Find comparable claims
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
        
    # LLM Severity Uplift based on diagnosis
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
        import json
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
    
    claim_state.update(result)
    return claim_state

# COMMAND ----------

if __name__ == "__main__":
    test_state = {"claim_id": "CLM-2026-10000", "extracted_data": {"claimed_amount": 50000, "diagnosis_icd": "J12.9"}, "coverage": {"coverage_status": "COVERED"}}
    res = agent4_reserve(test_state)
    import json
    print(json.dumps(res, indent=2))