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
from src.agents.utils import sanitize_document_text

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
            # Use @champion alias instead of /latest
            model = mlflow.xgboost.load_model("models:/health_claims_dev.claims.fraud_detection_xgboost@champion")
        except Exception:
            print(f"[Agent 2] ML model not found locally or in MLflow. Please run 04a_train_fraud_model.py first!")
            
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
        return 0.1

def agent2_fraud(claim_state: dict) -> dict:
    """
    Checks for fraud using ML structured features and LLM narrative checking.
    """
    claim_id = claim_state.get("claim_id")
    print(f"[Agent 2] Processing fraud detection for {claim_id}...")

    ml_score = get_ml_fraud_score(claim_state)
    
    file_path = f"{repo_root}/data/raw/unstructured/{claim_id}_discharge_summary.txt"
    document_text = ""
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            document_text = f.read()

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
    
    llm_fraud_score = 0.1
    signals = []
    reasoning = "Normal claim processing."
    try:
        start_idx = response_text.find("{")
        end_idx = response_text.rfind("}") + 1
        if start_idx != -1 and end_idx != -1:
            data = json.loads(response_text[start_idx:end_idx])
            llm_fraud_score = data.get("llm_fraud_score", 0.1)
            signals = data.get("narrative_signals", [])
            reasoning = data.get("reasoning", reasoning)
    except Exception as e:
        print(f"[Agent 2] JSON parse error: {e}")

    final_score = (ml_score * 0.6) + (llm_fraud_score * 0.4)
    confidence = "HIGH" if final_score > 0.6 else ("MEDIUM" if final_score > 0.3 else "LOW")
    
    result = {
        "fraud": {
            "fraud_score": round(final_score, 2),
            "confidence": confidence,
            "fraud_signals": signals,
            "reasoning": reasoning
        }
    }
    
    try:
        mlflow.log_metric(f"{claim_id}_ml_fraud_score", ml_score)
        mlflow.log_metric(f"{claim_id}_llm_fraud_score", llm_fraud_score)
        mlflow.log_metric(f"{claim_id}_final_fraud_score", result["fraud"]["fraud_score"])
        mlflow.log_param(f"{claim_id}_fraud_confidence", confidence)
    except Exception as e:
        print(f"[Agent 2] MLflow log error: {e}")
        
    claim_state.update(result)
    return claim_state
