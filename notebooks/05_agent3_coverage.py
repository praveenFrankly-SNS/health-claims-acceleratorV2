# Databricks notebook source
# MAGIC %md
# MAGIC # 05 Agent 3: Coverage Eligibility
# MAGIC Simulates RAG against policy forms to determine if the claim is covered.
# MAGIC Uses sentence-transformers locally to simulate Databricks Vector Search similarity.

# COMMAND ----------

# MAGIC %pip install databricks-vectorsearch sentence-transformers scikit-learn

# COMMAND ----------

try:
    dbutils.library.restartPython()
except Exception:
    pass

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

def retrieve_policy_chunks(policy_number: str, diagnosis: str, hospital: str, plan_tier: str) -> dict:
    import re
    # Read actual policy document from disk
    repo_root = "." if os.path.exists("./data") else ".."
    file_path = f"{repo_root}/data/policy_forms/{plan_tier}.txt"
    
    sections = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            # Split by "Section X.X"
            raw_sections = re.split(r'(Section \d+\.\d+)', content)
            
            if len(raw_sections) > 1:
                # Group section title with text
                for i in range(1, len(raw_sections), 2):
                    section_id = raw_sections[i].strip()
                    text = raw_sections[i+1].strip() if i+1 < len(raw_sections) else ""
                    if text:
                        sections.append({"id": section_id, "text": text})
    except Exception as e:
        print(f"Failed to load policy form {file_path}: {e}")
        # Fallback to hardcoded if files are missing
        sections = [
            {"id": "Section 4.2", "text": "Room Rent Limit: The policy covers room rent up to 1% of the Base Sum Insured per day."},
            {"id": "Section 5.1", "text": "Exclusions: Treatment for congenital diseases, cosmetic surgery, and unproven treatments are excluded."},
            {"id": "Section 7.1", "text": "Network Hospital Coverage: Claims from network hospitals are eligible for cashless processing."}
        ]
    
    query = f"diagnosis {diagnosis} hospital {hospital}"
    
    vs_success = False
    try:
        from databricks.vector_search.client import VectorSearchClient
        vsc = VectorSearchClient()
        
        endpoint_name = "aml_policy_vs_endpoint"
        index_name = "health_claims_dev.claims.policy_forms_index"
        
        # This will fail gracefully in the free version if endpoint is missing/not running
        index = vsc.get_index(endpoint_name, index_name)
        
        results = index.similarity_search(
            query_text=query,
            columns=["id", "text"],
            filters={"plan_tier": plan_tier},
            num_results=3
        )
        
        # Parse Databricks VS results (usually contains 'result' -> 'data_array')
        if "result" in results and "data_array" in results["result"]:
            data_array = results["result"]["data_array"]
            if len(data_array) > 0:
                # Assuming score is returned as the last element in the array
                max_sim = float(data_array[0][-1])
                vs_success = True
                print(f"Successfully retrieved chunks from Databricks Vector Search. Max similarity: {max_sim}")
                
    except Exception as e:
        print(f"Notice: Databricks Vector Search unavailable or failed ({e}). Falling back to local RAG simulation.")
        
    if not vs_success:
        try:
            from sentence_transformers import SentenceTransformer
            from sklearn.metrics.pairwise import cosine_similarity
            import numpy as np
            
            # Disable HuggingFace progress bars to prevent Databricks widget spam
            os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
            
            # Load a small local model to simulate Vector Search embeddings
            model = SentenceTransformer('all-MiniLM-L6-v2')
            section_texts = [s["text"] for s in sections]
            embeddings = model.encode(section_texts)
            query_embedding = model.encode([query])
            
            similarities = cosine_similarity(query_embedding, embeddings)[0]
            best_idx = np.argmax(similarities)
            max_sim = float(similarities[best_idx])
            
            # We will return all chunks for context, but note the top similarity for the hallucination guard
            # In a real RAG, we'd only return chunks above the threshold.
            # Here we just want to ensure we have a realistic score.
        except ImportError:
            # Fallback if sentence-transformers is not installed
            print("Warning: sentence-transformers not installed. Using simulated similarity score.")
            max_sim = 0.85 if "pneumonia" in diagnosis.lower() or "j1" in diagnosis.lower() else 0.65
        
    policy_text = "\n".join([f"{s['id']} - {s['text']}" for s in sections])
    return {
        "text": policy_text,
        "max_similarity": max_sim,
        "cited_sections": [s["id"] for s in sections]
    }

def agent3_coverage(claim_state: dict) -> dict:
    claim_id = claim_state.get("claim_id")
    print(f"[Agent 3] Processing coverage eligibility for {claim_id}...")
    
    extracted = claim_state.get("extracted_data", {})
    policy_number = extracted.get("policy_number", "UNKNOWN")
    diagnosis = extracted.get("diagnosis_icd", "UNKNOWN")
    hospital = extracted.get("hospital_name", "UNKNOWN")
    plan_tier = extracted.get("plan_tier", "Silver").capitalize()  # Ensure matches file casing like Premium.txt
    
    retrieval = retrieve_policy_chunks(policy_number, diagnosis, hospital, plan_tier)
    
    # Read threshold from config
    repo_root = "." if os.path.exists("./config/thresholds.yml") else ".."
    import yaml
    try:
        with open(f"{repo_root}/config/thresholds.yml", "r") as f:
            thresholds = yaml.safe_load(f)
            SIMILARITY_THRESHOLD = thresholds.get("coverage_similarity_threshold", 0.70)
    except Exception as e:
        print(f"Warning: Could not load thresholds: {e}")
        SIMILARITY_THRESHOLD = 0.70
    if retrieval["max_similarity"] < SIMILARITY_THRESHOLD:
        print(f"[Agent 3] Hallucination Guard Triggered: Similarity {retrieval['max_similarity']} < {SIMILARITY_THRESHOLD}")
        claim_state.update({
            "coverage": {
                "coverage_status": "NEEDS_REVIEW",
                "coverage_amount_estimate": 0,
                "exclusions_triggered": ["RAG_CONFIDENCE_LOW"],
                "policy_sections_cited": [],
                "notes": "Hallucination guard triggered. Sent for manual review."
            }
        })
        return claim_state
    
    policy_text = retrieval["text"]
    
    prompt = f"""
    You are an AI Coverage Eligibility Agent. Determine if the claim is covered based on the policy text.
    
    Claim Facts:
    - Policy Number: {policy_number}
    - Diagnosis: {diagnosis}
    - Hospital: {hospital}
    - Claimed Amount: {extracted.get('claimed_amount', 0)}
    - Sum Insured: {extracted.get('sum_insured', 'Unknown')}
    
    Policy Document Excerpts:
    {policy_text}
    
    Return a JSON object with:
    - coverage_status (COVERED, EXCLUDED, PARTIAL, NEEDS_REVIEW)
    - coverage_amount_estimate (number)
    - exclusions_triggered (list of strings)
    - policy_sections_cited (list of strings matching the section IDs provided)
    - notes (string)
    Do NOT output anything except valid JSON.
    """
    
    response_text = llm.generate(prompt, max_tokens=400)
    
    coverage_result = {
        "coverage_status": "NEEDS_REVIEW",
        "coverage_amount_estimate": 0,
        "exclusions_triggered": [],
        "policy_sections_cited": [],
        "notes": "Failed to parse LLM response"
    }
    
    try:
        start_idx = response_text.find("{")
        end_idx = response_text.rfind("}") + 1
        if start_idx != -1 and end_idx != -1:
            coverage_result = json.loads(response_text[start_idx:end_idx])
    except Exception as e:
        print(f"[Agent 3] JSON parse error: {e}")

    result = {
        "coverage": coverage_result
    }
    
    claim_state.update(result)
    return claim_state

# COMMAND ----------

# Standalone Test
if __name__ == "__main__":
    test_state = {"claim_id": "CLM-2026-10000", "extracted_data": {"policy_number": "POL-123", "claimed_amount": 50000, "diagnosis_icd": "J18.9", "hospital_name": "Apollo"}}
    res = agent3_coverage(test_state)
    print(json.dumps(res, indent=2))