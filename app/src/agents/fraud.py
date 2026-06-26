import os
import sys
import json
import importlib
import yaml
import mlflow

# Ensure config module is in path
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.append(repo_root)

import config.llm_client
importlib.reload(config.llm_client)
from config.llm_client import llm, FraudLLMOutput, FraudResult
from src.agents.utils import sanitize_document_text


def _load_thresholds() -> dict:
    """Load thresholds from config — single source of truth for blend weights."""
    thresholds_path = os.path.join(repo_root, "config", "thresholds.yml")
    try:
        with open(thresholds_path, "r") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"[Agent 2] Warning: Could not load thresholds.yml: {e}")
        return {}


def _lookup_provider_info(physician_reg_no: str, spark=None) -> dict:
    """
    Lookup physician in provider_registry to surface blacklist_status
    and historical_fraud_flag_ratio into the fraud result so the allocation
    step can read the override flag without a second registry lookup.
    """
    if not physician_reg_no:
        return {"blacklist_status": False, "physician_fraud_ratio": 0.0}
    try:
        if spark is None:
            try:
                from databricks.connect import DatabricksSession
                cluster_id = os.environ.get("DATABRICKS_CLUSTER_ID")
                builder = DatabricksSession.builder
                if cluster_id:
                    builder = builder.clusterId(cluster_id)
                else:
                    builder = builder.serverless()
                spark = builder.getOrCreate()
            except Exception as connect_err:
                print(f"[Agent 2] Databricks Connect fallback failed: {connect_err}")
                from pyspark.sql import SparkSession
                spark = SparkSession.builder.getOrCreate()

        df_providers = spark.table("health_claims_dev.claims.provider_registry")
        row = df_providers.filter(
            df_providers.physician_registration_number == physician_reg_no
        ).collect()

        if row:
            return {
                "blacklist_status": bool(row[0].blacklist_status),
                "physician_fraud_ratio": float(row[0].historical_fraud_flag_ratio or 0.0),
            }
    except Exception as e:
        print(f"[Agent 2] Provider lookup failed: {e}")

    return {"blacklist_status": False, "physician_fraud_ratio": 0.0}


def get_ml_fraud_score(claim_state: dict) -> float:
    import pandas as pd
    import pickle
    
    extracted = claim_state.get("extracted_data", {})
    amount = float(extracted.get("claimed_amount", 0))
    
    model = None
    local_model_path = f"{repo_root}/models/fraud_xgboost.pkl"
    
    if os.path.exists(local_model_path):
        try:
            with open(local_model_path, "rb") as f:
                model = pickle.load(f)
        except Exception as e:
            print(f"[Agent 2] Could not load local ML model: {e}")
    else:
        try:
            import logging
            logging.getLogger("pyspark.sql.connect.client.core").setLevel(logging.CRITICAL)
            mlflow.set_registry_uri("databricks-uc")
            # Use @champion alias instead of /latest
            model = mlflow.xgboost.load_model("models:/health_claims_dev.claims.fraud_detection_xgboost@champion")
        except Exception as e:
            print(f"[Agent 2] ML model not found locally or in MLflow. Exact Error: {e}")
            
    premium = float(extracted.get("premium_paid", 12000))
    if premium == 0: premium = 1
    
    features = {
        'claimed_amount': [amount],
        'amount_to_premium_ratio': [claim_state.get("amount_to_premium_ratio", amount / premium)],
        'days_since_inception': [claim_state.get("days_since_inception", 500)],
        'claim_velocity': [claim_state.get("claim_velocity", 0)]
    }
    
    df_features = pd.DataFrame(features)
    
    try:
        prob = model.predict_proba(df_features)[0][1]
        return float(prob)
    except Exception as e:
        print(f"[Agent 2] ML Prediction failed: {e}")
        return -1.0

def agent2_fraud(claim_state: dict, spark=None) -> dict:
    """
    Checks for fraud using ML structured features and LLM narrative checking.
    
    v2 fixes:
    - Reads blend weights (fraud_weight_ml, fraud_weight_llm) from thresholds.yml
      instead of the hardcoded 0.6/0.4 that silently ignored the config.
    - Surfaces blacklist_status and physician_fraud_ratio from provider_registry
      into the result so adjuster_allocation can read the override flag directly.
    """
    claim_id = claim_state.get("claim_id")
    print(f"[Agent 2] Processing fraud detection for {claim_id}...")

    # Load blend weights from config — single source of truth
    thresholds = _load_thresholds()
    weight_ml = thresholds.get("fraud_weight_ml", 0.60)
    weight_llm = thresholds.get("fraud_weight_llm", 0.40)

    ml_score = get_ml_fraud_score(claim_state)
    
    catalog = os.environ.get("CATALOG_NAME", "health_claims_dev")
    schema = os.environ.get("SCHEMA_NAME", "claims")
    raw_docs_vol = os.environ.get("RAW_DOCUMENTS_VOLUME_PATH", f"/Volumes/{catalog}/{schema}/raw_documents")
    paths_to_try = [
        f"{repo_root}/data/raw/unstructured/{claim_id}_discharge_summary.txt",
        f"{repo_root}/data/raw/unstructured/{claim_id}_discharge_summary.pdf",
        # UC Volume root
        f"{raw_docs_vol}/{claim_id}_discharge_summary.pdf",
        f"{raw_docs_vol}/{claim_id}_discharge_summary.txt",
        f"/dbfs{raw_docs_vol}/{claim_id}_discharge_summary.pdf",
        f"/dbfs{raw_docs_vol}/{claim_id}_discharge_summary.txt",
        # UC Volume subdirectories
        f"{raw_docs_vol}/discharge-summaries/{claim_id}_discharge_summary.txt",
        f"{raw_docs_vol}/discharge-summaries/{claim_id}_discharge_summary.pdf",
        f"{raw_docs_vol}/discharge summaries/{claim_id}_discharge_summary.txt",
        f"{raw_docs_vol}/discharge summaries/{claim_id}_discharge_summary.pdf",
        f"/dbfs{raw_docs_vol}/discharge-summaries/{claim_id}_discharge_summary.txt",
        f"/dbfs{raw_docs_vol}/discharge-summaries/{claim_id}_discharge_summary.pdf",
        f"/dbfs{raw_docs_vol}/discharge summaries/{claim_id}_discharge_summary.txt",
        f"/dbfs{raw_docs_vol}/discharge summaries/{claim_id}_discharge_summary.pdf",
    ]
    
    document_text = ""
    for path in paths_to_try:
        if os.path.exists(path):
            try:
                if path.endswith(".pdf"):
                    with open(path, "rb") as f:
                        raw = f.read()
                    import PyPDF2
                    from io import BytesIO
                    reader = PyPDF2.PdfReader(BytesIO(raw))
                    document_text = "\n".join(page.extract_text() for page in reader.pages)
                else:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        document_text = f.read()
                if document_text.strip():
                    break
            except Exception as e:
                print(f"[Agent 2] Failed to read narrative from {path}: {e}")

    sanitized_doc = sanitize_document_text(document_text, 4000)

    prompt = f"""
    You are an AI Fraud Detection Agent. Analyze the following medical discharge summary for inconsistencies.
    Look for: upcoding, unbundling, inflated room rent, or contradictory statements.
    
    Document:
    {sanitized_doc}
    
    Return a JSON object with:
    - llm_fraud_score (float 0-1)
    - narrative_signals (list of strings describing any red flags found, or empty list if none)
    - reasoning (string explaining why this score was given based on the signals and the document)
    Do NOT output anything except valid JSON.
    """
    
    response_text = llm.generate(prompt, max_tokens=300)
    
    # Parse LLM response into typed model
    llm_output = FraudLLMOutput()
    try:
        start_idx = response_text.find("{")
        end_idx = response_text.rfind("}") + 1
        if start_idx != -1 and end_idx != -1:
            data = json.loads(response_text[start_idx:end_idx])
            llm_output = FraudLLMOutput(**data)
    except Exception as e:
        print(f"[Agent 2] JSON parse error: {e}")

    # Blend scores using weights from config
    if ml_score == -1.0:
        final_score = llm_output.llm_fraud_score
    else:
        final_score = (ml_score * weight_ml) + (llm_output.llm_fraud_score * weight_llm)
        
    confidence = "HIGH" if final_score > 0.6 else ("MEDIUM" if final_score > 0.3 else "LOW")
    
    # Lookup provider info to surface blacklist_status
    extracted = claim_state.get("extracted_data", {})
    physician_reg_no = extracted.get("attending_physician_registration_number")
    provider_info = _lookup_provider_info(physician_reg_no, spark)

    fraud_result = FraudResult(
        fraud_score=round(final_score, 2),
        confidence=confidence,
        fraud_signals=llm_output.narrative_signals,
        reasoning=llm_output.reasoning,
        ml_score=round(ml_score, 4),
        llm_score=round(llm_output.llm_fraud_score, 4),
        blacklist_status=provider_info["blacklist_status"],
        physician_fraud_ratio=provider_info["physician_fraud_ratio"],
    )

    result = {
        "fraud": fraud_result.model_dump()
    }
    
    try:
        mlflow.log_metric(f"{claim_id}_ml_fraud_score", ml_score)
        mlflow.log_metric(f"{claim_id}_llm_fraud_score", llm_output.llm_fraud_score)
        mlflow.log_metric(f"{claim_id}_final_fraud_score", fraud_result.fraud_score)
        mlflow.log_param(f"{claim_id}_fraud_confidence", confidence)
        mlflow.log_param(f"{claim_id}_blacklist_status", str(provider_info["blacklist_status"]))
    except Exception as e:
        print(f"[Agent 2] MLflow log error: {e}")
        
    claim_state.update(result)
    return claim_state
