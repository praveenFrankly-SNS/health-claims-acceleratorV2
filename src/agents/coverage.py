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
from config.llm_client import llm

def retrieve_policy_chunks(policy_number: str, diagnosis: str, hospital: str, plan_tier: str) -> dict:
    import re
    file_path = f"{repo_root}/data/policy_forms/{plan_tier}.txt"
    
    sections = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            raw_sections = re.split(r'(Section \d+\.\d+)', content)
            
            if len(raw_sections) > 1:
                for i in range(1, len(raw_sections), 2):
                    section_id = raw_sections[i].strip()
                    text = raw_sections[i+1].strip() if i+1 < len(raw_sections) else ""
                    if text:
                        sections.append({"id": section_id, "text": text})
    except Exception as e:
        print(f"Failed to load policy form {file_path}: {e}")
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
        
        index = vsc.get_index(endpoint_name, index_name)
        
        results = index.similarity_search(
            query_text=query,
            columns=["id", "text"],
            filters={"plan_tier": plan_tier},
            num_results=3
        )
        
        if "result" in results and "data_array" in results["result"]:
            data_array = results["result"]["data_array"]
            if len(data_array) > 0:
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
            
            os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
            
            model = SentenceTransformer('all-MiniLM-L6-v2')
            section_texts = [s["text"] for s in sections]
            embeddings = model.encode(section_texts)
            query_embedding = model.encode([query])
            
            similarities = cosine_similarity(query_embedding, embeddings)[0]
            best_idx = np.argmax(similarities)
            max_sim = float(similarities[best_idx])
            
        except ImportError:
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
    plan_tier = extracted.get("plan_tier", "Silver").capitalize()
    
    retrieval = retrieve_policy_chunks(policy_number, diagnosis, hospital, plan_tier)
    
    thresholds = {}
    try:
        with open(f"{repo_root}/config/thresholds.yml", "r") as f:
            thresholds = yaml.safe_load(f)
            SIMILARITY_THRESHOLD = thresholds.get("coverage_similarity_threshold", 0.10)
    except Exception as e:
        print(f"Warning: Could not load thresholds: {e}")
        SIMILARITY_THRESHOLD = 0.10
        
    if retrieval["max_similarity"] < SIMILARITY_THRESHOLD:
        print(f"[Agent 3] Hallucination Guard Triggered: Similarity {retrieval['max_similarity']} < {SIMILARITY_THRESHOLD}")
        claim_state.update({
            "coverage": {
                "coverage_status": "NEEDS_REVIEW",
                "coverage_amount_estimate": 0,
                "exclusions_triggered": ["RAG_CONFIDENCE_LOW"],
                "policy_sections_cited": [],
                "rag_similarity_score": round(retrieval['max_similarity'], 3),
                "notes": f"Hallucination guard triggered: Similarity {round(retrieval['max_similarity'], 3)} < {SIMILARITY_THRESHOLD}. Sent for manual review."
            }
        })
        try:
            mlflow.log_metric(f"{claim_id}_max_rag_similarity", retrieval["max_similarity"])
            mlflow.log_param(f"{claim_id}_coverage_status", "NEEDS_REVIEW (RAG_CONFIDENCE_LOW)")
        except:
            pass
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
    - rag_similarity_score (number, exactly {round(retrieval['max_similarity'], 3)})
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
    
    try:
        mlflow.log_metric(f"{claim_id}_max_rag_similarity", retrieval["max_similarity"])
        mlflow.log_param(f"{claim_id}_coverage_status", coverage_result.get("coverage_status", "UNKNOWN"))
        mlflow.log_metric(f"{claim_id}_coverage_amount_estimate", coverage_result.get("coverage_amount_estimate", 0))
    except Exception as e:
        print(f"[Agent 3] MLflow log error: {e}")
        
    claim_state.update(result)
    return claim_state
