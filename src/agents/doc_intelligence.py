import os
import json
import sys
import importlib
import mlflow

# Ensure config module is in path
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.append(repo_root)

import config.llm_client
importlib.reload(config.llm_client)
from config.llm_client import llm
from src.agents.utils import sanitize_document_text

def agent1_doc_intelligence(claim_state: dict, spark=None) -> dict:
    """
    Reads the discharge summary from the local volume/path and uses the LLM to extract fields.
    """
    claim_id = claim_state.get("claim_id")
    if not claim_id:
        return {"error": "No claim_id provided"}

    print(f"[Agent 1] Processing document extraction for {claim_id}...")
    
    file_path = f"{repo_root}/data/raw/unstructured/{claim_id}_discharge_summary.txt"
    try:
        with open(file_path, "r") as f:
            document_text = f.read()
    except FileNotFoundError:
        document_text = ""

    if not document_text:
        return {"completeness_score": 0.0, "missing_fields": ["discharge_summary"], "extracted_data": {}}

    sanitized_doc = sanitize_document_text(document_text, 4000)

    prompt = f"""
    You are an AI Document Intelligence Agent for health insurance.
    Extract the following fields from the discharge summary provided:
    - policy_number
    - claimant_name
    - admission_date
    - discharge_date
    - hospital_name
    - diagnosis_icd
    - claimed_amount
    - attending_physician_registration_number
    
    Return a JSON object containing these keys. If a field is not found, leave it as null.
    Do NOT output anything except valid JSON.
    
    Document:
    {sanitized_doc}
    """
    
    response_text = llm.generate(prompt, max_tokens=500)
    
    extracted_data = {}
    try:
        start_idx = response_text.find("{")
        end_idx = response_text.rfind("}") + 1
        if start_idx != -1 and end_idx != -1:
            extracted_data = json.loads(response_text[start_idx:end_idx])
    except Exception as e:
        print(f"[Agent 1] JSON parse error: {e}")

    required_fields = ["policy_number", "claimant_name", "admission_date", "discharge_date", 
                       "hospital_name", "diagnosis_icd", "claimed_amount", "attending_physician_registration_number"]
    
    missing_fields = [f for f in required_fields if not extracted_data.get(f)]
    completeness_score = (len(required_fields) - len(missing_fields)) / len(required_fields)
    
    # CROSS-VALIDATION
    cross_val_status = "UNKNOWN"
    policy_number = extracted_data.get("policy_number")
    claimant_name = extracted_data.get("claimant_name")
    
    if policy_number:
        try:
            if spark is None:
                from pyspark.sql import SparkSession
                spark = SparkSession.builder.getOrCreate()
            df_policy = spark.table("health_claims_dev.claims.policy_master")
            
            policy_row = df_policy.filter(df_policy.policy_number == policy_number).collect()
            if not policy_row:
                cross_val_status = "FAILED_POLICY_NOT_FOUND"
            else:
                row = policy_row[0]
                if row.status != "ACTIVE":
                    cross_val_status = "FAILED_POLICY_LAPSED"
                elif claimant_name and claimant_name.lower() not in row.claimant_name.lower() and row.claimant_name.lower() not in claimant_name.lower():
                    cross_val_status = "FAILED_NAME_MISMATCH"
                else:
                    cross_val_status = "PASSED"
                    extracted_data["plan_tier"] = row.plan_tier
                    extracted_data["sum_insured"] = row.sum_insured
                    extracted_data["premium_paid"] = row.premium_paid
        except Exception as e:
            error_msg = f"[Agent 1] Cross-validation failed to run: {e}"
            print(error_msg)
            cross_val_status = "SKIPPED_DUE_TO_ERROR"
            extracted_data["cross_validation_error"] = str(e)

    result = {
        "completeness_score": round(completeness_score, 2),
        "missing_fields": missing_fields,
        "cross_validation_status": cross_val_status,
        "extracted_data": extracted_data
    }
    
    try:
        mlflow.log_param(f"{claim_id}_agent1_cross_val_status", cross_val_status)
        mlflow.log_metric(f"{claim_id}_agent1_completeness_score", result["completeness_score"])
    except Exception as e:
        print(f"[Agent 1] MLflow log error: {e}")
        
    claim_state.update(result)
    return claim_state
