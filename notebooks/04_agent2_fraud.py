# Databricks notebook source
# MAGIC %md
# MAGIC # 04 Agent 2: Fraud Signal Detection
# MAGIC Uses a mock ML model for structured features and LLM for narrative consistency check.

# COMMAND ----------

# MAGIC %pip install xgboost pandas mlflow

# COMMAND ----------

try:
    dbutils.library.restartPython()
except Exception:
    pass

# COMMAND ----------

import os
import sys
import random
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

def get_ml_fraud_score(claim_state: dict) -> float:
    import pandas as pd
    import mlflow
    import pickle
    import os
    
    # Extract features from state
    extracted = claim_state.get("extracted_data", {})
    amount = float(extracted.get("claimed_amount", 0))
    
    # Try to load the trained model (prioritize local pickle for Free Edition)
    model = None
    repo_root = "." if os.path.exists("./models") else ".."
    local_model_path = f"{repo_root}/models/fraud_xgboost.pkl"
    
    if model is not None:
        try:
            prob = model.predict_proba(df_features)[0][1]
            return float(prob)
        except Exception:
            pass

    # Deterministic feature risk scoring fallback if ML model is unavailable
    ratio = float(claim_state.get("amount_to_premium_ratio", amount / premium if premium > 0 else 0.5))
    velocity = float(claim_state.get("claim_velocity", 0))
    if ratio > 0.8 or velocity > 2:
        return 0.85
    elif ratio > 0.5:
        return 0.45
    return 0.15

def agent2_fraud(claim_state: dict) -> dict:
    """
    Checks for fraud using ML structured features and LLM narrative checking.
    """
    claim_id = claim_state.get("claim_id")
    print(f"[Agent 2] Processing fraud detection for {claim_id}...")

    ml_score = get_ml_fraud_score(claim_state)
    
    # Try UC Volume first, then local development paths
    catalog = "health_claims_dev"
    schema = "claims"
    try:
        dbutils.widgets.text("catalog", "health_claims_dev")
        dbutils.widgets.text("schema", "claims")
        catalog = dbutils.widgets.get("catalog")
        schema = dbutils.widgets.get("schema")
    except Exception:
        pass

    # LLM Narrative Check
    repo_root = "."
    if os.path.exists("./data/raw/unstructured"):
        repo_root = "."
    elif os.path.exists("../data/raw/unstructured"):
        repo_root = ".."
    else:
        repo_root = "."

    paths_to_try = [
        f"{repo_root}/data/raw/unstructured/{claim_id}_discharge_summary.txt",
        f"{repo_root}/data/raw/unstructured/{claim_id}_discharge_summary.pdf",
        f"/Volumes/{catalog}/{schema}/raw_documents/discharge-summaries/{claim_id}_discharge_summary.txt",
        f"/Volumes/{catalog}/{schema}/raw_documents/discharge-summaries/{claim_id}_discharge_summary.pdf",
        f"/Volumes/{catalog}/{schema}/raw_documents/discharge summaries/{claim_id}_discharge_summary.txt",
        f"/Volumes/{catalog}/{schema}/raw_documents/discharge summaries/{claim_id}_discharge_summary.pdf",
        f"/dbfs/Volumes/{catalog}/{schema}/raw_documents/discharge-summaries/{claim_id}_discharge_summary.txt",
        f"/dbfs/Volumes/{catalog}/{schema}/raw_documents/discharge-summaries/{claim_id}_discharge_summary.pdf",
        f"/dbfs/Volumes/{catalog}/{schema}/raw_documents/discharge summaries/{claim_id}_discharge_summary.txt",
        f"/dbfs/Volumes/{catalog}/{schema}/raw_documents/discharge summaries/{claim_id}_discharge_summary.pdf",
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

    prompt = f"""
    You are an AI Fraud Detection Agent. Analyze the following medical discharge summary for inconsistencies.
    Look for: upcoding, unbundling, inflated room rent, or contradictory statements.
    
    Document:
    {document_text}
    
    Return a JSON object with:
    - llm_fraud_score (float 0-1)
    - narrative_signals (list of strings describing any red flags found, or empty list if none)
    Do NOT output anything except valid JSON.
    """
    
    response_text = llm.generate(prompt, max_tokens=300)
    
    llm_fraud_score = 0.1
    signals = []
    try:
        start_idx = response_text.find("{")
        end_idx = response_text.rfind("}") + 1
        if start_idx != -1 and end_idx != -1:
            data = json.loads(response_text[start_idx:end_idx])
            llm_fraud_score = data.get("llm_fraud_score", 0.1)
            signals = data.get("narrative_signals", [])
    except Exception as e:
        print(f"[Agent 2] JSON parse error: {e}")

    final_score = (ml_score * 0.6) + (llm_fraud_score * 0.4)
    confidence = "HIGH" if final_score > 0.6 else ("MEDIUM" if final_score > 0.3 else "LOW")
    
    result = {
        "fraud": {
            "fraud_score": round(final_score, 2),
            "confidence": confidence,
            "fraud_signals": signals
        }
    }
    
    claim_state.update(result)
    return claim_state

# COMMAND ----------

# Standalone Test
if __name__ == "__main__":
    test_state = {"claim_id": "CLM-2026-10000", "extracted_data": {"claimed_amount": 250000}}
    res = agent2_fraud(test_state)
    import json
    print(json.dumps(res, indent=2))