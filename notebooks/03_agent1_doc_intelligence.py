# Databricks notebook source
# MAGIC %md
# MAGIC # 03 Agent 1: Document Intelligence
# MAGIC Extracts structured data and computes completeness score from unstructured claims submissions (PDFs/Text).

# COMMAND ----------

import os
import json
import sys

import sys
import importlib

# Ensure config module is in path
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

def agent1_doc_intelligence(claim_state: dict) -> dict:
    """
    Reads the discharge summary from the local volume/path and uses the LLM to extract fields.
    """
    claim_id = claim_state.get("claim_id")
    if not claim_id:
        return {"error": "No claim_id provided"}

    print(f"[Agent 1] Processing document extraction for {claim_id}...")
    
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

    repo_root = "."
    if os.path.exists("./data/raw/unstructured"):
        repo_root = "."
    elif os.path.exists("../data/raw/unstructured"):
        repo_root = ".."
    else:
        repo_root = "."

    def _read_pdf_text(raw_bytes: bytes) -> str:
        """Try multiple PDF extraction methods — fpdf2-generated PDFs need pypdf not PyPDF2."""
        from io import BytesIO
        try:
            import pypdf
            reader = pypdf.PdfReader(BytesIO(raw_bytes))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            if text.strip():
                return text
        except Exception:
            pass
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(BytesIO(raw_bytes))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            if text.strip():
                return text
        except Exception:
            pass
        return ""

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
        try:
            # Use open() directly — os.path.exists() can fail on UC Volume subdirs
            # even when the file is actually readable
            if path.endswith(".pdf"):
                with open(path, "rb") as f:
                    document_text = _read_pdf_text(f.read())
            else:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    document_text = f.read()
            if document_text.strip():
                print(f"[Agent 1] Loaded document from: {path}")
                break
        except (FileNotFoundError, OSError):
            continue
        except Exception as e:
            print(f"[Agent 1] Failed to read from {path}: {e}")
            continue

    if not document_text.strip():
        print(f"[Agent 1] No discharge summary found for {claim_id} in any volume path.")
        return {"completeness_score": 0.0, "missing_fields": ["discharge_summary"], "extracted_data": {}}

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
    {document_text}
    """
    
    response_text = llm.generate(prompt, max_tokens=500)
    
    # Simple JSON extraction
    extracted_data = {}
    try:
        # Very simple parse (assuming LLM returns pure JSON)
        start_idx = response_text.find("{")
        end_idx = response_text.rfind("}") + 1
        if start_idx != -1 and end_idx != -1:
            extracted_data = json.loads(response_text[start_idx:end_idx])
    except Exception as e:
        print(f"[Agent 1] JSON parse error: {e}")

    # Calculate completeness score based on required fields
    required_fields = ["policy_number", "claimant_name", "admission_date", "discharge_date", 
                       "hospital_name", "diagnosis_icd", "claimed_amount", "attending_physician_registration_number"]
    
    missing_fields = [f for f in required_fields if not extracted_data.get(f)]
    
    completeness_score = (len(required_fields) - len(missing_fields)) / len(required_fields)
    
    # CROSS-VALIDATION against policy_master
    cross_val_status = "UNKNOWN"
    policy_number = extracted_data.get("policy_number")
    claimant_name = extracted_data.get("claimant_name")
    
    if policy_number:
        try:
            from pyspark.sql import SparkSession
            spark = SparkSession.builder.getOrCreate()
            df_policy = spark.table("health_claims_dev.claims.policy_master")
            
            # Check if policy exists, is active, and name matches roughly
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
                    # enriching with sum insured and plan tier
                    extracted_data["plan_tier"] = row.plan_tier
                    extracted_data["sum_insured"] = row.sum_insured
                    extracted_data["premium_paid"] = row.premium_paid
        except Exception as e:
            print(f"[Agent 1] Cross-validation failed to run: {e}")
            cross_val_status = "SKIPPED_DUE_TO_ERROR"

    result = {
        "completeness_score": round(completeness_score, 2),
        "missing_fields": missing_fields,
        "cross_validation_status": cross_val_status,
        "extracted_data": extracted_data
    }
    
    # Update the claim state
    claim_state.update(result)
    return claim_state

# COMMAND ----------

# Standalone Test
if __name__ == "__main__":
    test_state = {"claim_id": "CLM-2026-10000"}
    res = agent1_doc_intelligence(test_state)
    print(json.dumps(res, indent=2))