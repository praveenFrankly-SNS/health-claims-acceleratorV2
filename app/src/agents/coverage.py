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
from config.llm_client import llm, CoverageResult


# ---------------------------------------------------------------------------
# Deterministic Coverage Pipeline — no LLM, pure math
# ---------------------------------------------------------------------------

def _get_policy_forms_dir() -> str:
    """Resolve the directory containing policy form files, falling back to UC Volume on Databricks."""
    local_dir = os.path.join(repo_root, "data", "policy_forms")
    if os.path.exists(local_dir):
        return local_dir
    
    catalog = os.environ.get("CATALOG_NAME", "health_claims_dev")
    schema = os.environ.get("SCHEMA_NAME", "claims")
    vol_dir = os.environ.get("POLICY_FORMS_VOLUME_PATH", f"/Volumes/{catalog}/{schema}/policy_forms")
    if os.path.exists(vol_dir):
        return vol_dir
    
    dbfs_vol_dir = f"/dbfs{vol_dir}" if not vol_dir.startswith("/dbfs") else vol_dir
    if os.path.exists(dbfs_vol_dir):
        return dbfs_vol_dir
        
    return local_dir


def _load_policy_form_metadata(plan_tier: str, form_version: str) -> dict:
    """Load structured JSON metadata for deterministic checks."""
    policy_forms_dir = _get_policy_forms_dir()
    json_path = os.path.join(policy_forms_dir, f"{plan_tier}_{form_version}_metadata.json")
    try:
        with open(json_path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[Agent 3] Policy form metadata not found: {json_path}")
        return {}


def _compute_deterministic_deductions(extracted: dict, claim_bills: list,
                                       form_meta: dict) -> dict:
    """
    Deterministic deduction pipeline:
    1. Co-pay application (age-based, condition-based, network-based)
    2. Room rent cap detection with proportionate-deduction cascade
    3. Waiting period check (per-member coverage_start_date)
    4. Sub-limit caps by ICD/procedure category
    
    Returns a dict with all deterministic findings. No LLM is involved here.
    """
    deductions = {
        "copay_pct": 0.0,
        "copay_reason": None,
        "room_rent_excess": 0,
        "proportionate_deduction_applied": False,
        "proportionate_deduction_factor": 1.0,
        "waiting_period_violated": False,
        "waiting_period_reason": None,
        "sub_limit_triggered": False,
        "sub_limit_cap": None,
        "total_deterministic_deduction": 0,
    }

    if not form_meta:
        return deductions

    sum_insured = extracted.get("sum_insured", 0) or 0
    claimed_amount = extracted.get("claimed_amount", 0) or 0
    diagnosis_icd = extracted.get("diagnosis_icd", "")

    # --- 1. Co-pay ---
    # Senior citizen co-pay
    copay = 0.0
    copay_reason = []

    senior_copay = form_meta.get("senior_citizen_copay", 0)
    senior_age = form_meta.get("senior_citizen_age_threshold", 60)
    # Age check would require member DOB — use extracted data if available
    # For now, if member_age is in claim_state, use it
    member_age = extracted.get("member_age")
    if member_age and member_age >= senior_age and senior_copay > 0:
        copay = max(copay, senior_copay)
        copay_reason.append(f"Senior citizen ({member_age}yr) copay: {int(senior_copay*100)}%")

    # Condition-based co-pay (respiratory, cardiovascular)
    resp_copay = form_meta.get("respiratory_copay", 0)
    cardio_copay = form_meta.get("cardiovascular_copay", 0)
    if diagnosis_icd and diagnosis_icd.startswith("J") and resp_copay > 0:
        copay = max(copay, resp_copay)
        copay_reason.append(f"Respiratory condition copay: {int(resp_copay*100)}%")
    if diagnosis_icd and diagnosis_icd.startswith("I") and cardio_copay > 0:
        copay = max(copay, cardio_copay)
        copay_reason.append(f"Cardiovascular condition copay: {int(cardio_copay*100)}%")

    # Non-network co-pay (check hospital network status)
    non_network_copay = form_meta.get("non_network_copay", 0)
    hospital_network = extracted.get("hospital_network_status")
    if hospital_network == "OUT-OF-NETWORK" and non_network_copay > 0:
        copay = max(copay, non_network_copay)
        copay_reason.append(f"Non-network facility deduction: {int(non_network_copay*100)}%")

    deductions["copay_pct"] = copay
    deductions["copay_reason"] = "; ".join(copay_reason) if copay_reason else None

    # --- 2. Room Rent Cap & Proportionate Deduction ---
    room_rent_cap_pct = form_meta.get("room_rent_cap_pct")
    if room_rent_cap_pct is not None and sum_insured > 0:
        daily_cap = sum_insured * room_rent_cap_pct
        room_rent_bills = [b for b in claim_bills
                           if b.get("normalized_expense_type") == "ROOM_RENT"]
        if room_rent_bills:
            # Assume 1 room rent bill line = total room charges
            room_total = sum(b.get("amount", 0) for b in room_rent_bills)
            # Use admission/discharge for LOS
            from datetime import datetime
            los_days = 1
            try:
                adm = datetime.strptime(extracted.get("admission_date", ""), "%Y-%m-%d")
                dis = datetime.strptime(extracted.get("discharge_date", ""), "%Y-%m-%d")
                los_days = max((dis - adm).days, 1)
            except (ValueError, TypeError):
                pass

            actual_daily = room_total / los_days
            if actual_daily > daily_cap:
                deductions["room_rent_excess"] = int((actual_daily - daily_cap) * los_days)
                # Proportionate deduction cascade
                if form_meta.get("proportionate_deduction_applies", False):
                    proportion_factor = daily_cap / actual_daily
                    deductions["proportionate_deduction_applied"] = True
                    deductions["proportionate_deduction_factor"] = round(proportion_factor, 4)

    # --- 3. Waiting Period Check (per-member, not per-policy) ---
    specific_waiting_months = form_meta.get("specific_disease_waiting_months", 0)
    specific_conditions = form_meta.get("specific_disease_waiting_conditions", [])
    ped_waiting_months = form_meta.get("pre_existing_disease_waiting_months", 0)

    # Check if diagnosis is in the specific disease waiting list
    if diagnosis_icd in specific_conditions and specific_waiting_months > 0:
        # The clock starts from the MEMBER's coverage_start_date, not the policy inception
        coverage_start = extracted.get("member_coverage_start_date")
        if coverage_start:
            from datetime import datetime
            try:
                cov_start_dt = datetime.strptime(coverage_start, "%Y-%m-%d")
                admission_dt = datetime.strptime(extracted.get("admission_date", ""), "%Y-%m-%d")
                months_covered = (admission_dt - cov_start_dt).days / 30.44
                if months_covered < specific_waiting_months:
                    deductions["waiting_period_violated"] = True
                    deductions["waiting_period_reason"] = (
                        f"Condition {diagnosis_icd} has {specific_waiting_months}-month waiting period; "
                        f"member covered only {int(months_covered)} months since {coverage_start}"
                    )
            except (ValueError, TypeError):
                pass

    # --- 4. Sub-limits ---
    sub_limits = form_meta.get("sub_limits", [])
    for sl in sub_limits:
        if diagnosis_icd in sl.get("icd_codes", []):
            if sl["cap_type"] == "FIXED":
                cap = sl["value"]
            elif sl["cap_type"] == "PCT_SUM_INSURED":
                cap = int(sum_insured * sl["value"])
            else:
                continue
            if claimed_amount > cap:
                deductions["sub_limit_triggered"] = True
                deductions["sub_limit_cap"] = cap

    # --- Total deterministic deduction ---
    total_deduction = 0
    if copay > 0:
        total_deduction += int(claimed_amount * copay)
    total_deduction += deductions.get("room_rent_excess", 0)
    if deductions.get("sub_limit_triggered") and deductions.get("sub_limit_cap"):
        excess = max(0, claimed_amount - deductions["sub_limit_cap"])
        total_deduction += excess
    deductions["total_deterministic_deduction"] = total_deduction

    return deductions


# ---------------------------------------------------------------------------
# Semantic Coverage Pipeline — Vector Search / local RAG for fuzzy exclusions
# ---------------------------------------------------------------------------

def retrieve_policy_chunks(policy_number: str, diagnosis: str,
                           hospital: str, plan_tier: str) -> dict:
    """Retrieves policy clause chunks via Vector Search or local RAG fallback."""
    import re
    policy_forms_dir = _get_policy_forms_dir()
    file_path = os.path.join(policy_forms_dir, f"{plan_tier}.txt")
    
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
    max_sim = 0.0
    try:
        from databricks.vector_search.client import VectorSearchClient
        vsc = VectorSearchClient()
        
        endpoint_name = "shared_vs_endpoint"
        catalog = os.environ.get("CATALOG_NAME", "health_claims_dev")
        schema = os.environ.get("SCHEMA_NAME", "claims")
        index_name = f"{catalog}.{schema}.policy_forms_index"
        
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
            best_idx = int(np.argmax(similarities))
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


# ---------------------------------------------------------------------------
# Agent 3 Entry Point — Hybrid Pipeline
# ---------------------------------------------------------------------------

def agent3_coverage(claim_state: dict) -> dict:
    """
    Coverage eligibility agent — hybrid pipeline:
    1. Deterministic: copays, waiting periods, room rent caps, sub-limits (no LLM)
    2. Semantic: Vector Search for fuzzy exclusion clauses (LLM only for ambiguous cases)
    """
    claim_id = claim_state.get("claim_id")
    print(f"[Agent 3] Processing coverage eligibility for {claim_id}...")
    
    extracted = claim_state.get("extracted_data", {})
    policy_number = extracted.get("policy_number", "UNKNOWN")
    diagnosis = extracted.get("diagnosis_icd", "UNKNOWN")
    hospital = extracted.get("hospital_name", "UNKNOWN")
    plan_tier = extracted.get("plan_tier", "Silver").capitalize()
    form_version = extracted.get("policy_form_version", "v1.0")
    
    # --- Step 1: Deterministic Pipeline ---
    form_meta = _load_policy_form_metadata(plan_tier, form_version)

    # Get bill lines for this claim (from claim_state or load from CSV)
    claim_bills = claim_state.get("claim_bills", [])
    if not claim_bills:
        import csv
        bills_path = os.path.join(repo_root, "data", "raw", "structured", "claim_bills.csv")
        try:
            with open(bills_path, "r") as f:
                reader = csv.DictReader(f)
                claim_bills = [
                    {**row, "amount": int(row.get("amount", 0))}
                    for row in reader
                    if row.get("claim_id") == claim_id
                ]
        except Exception:
            pass

    deterministic = _compute_deterministic_deductions(extracted, claim_bills, form_meta)

    # If waiting period is violated, short-circuit — no need for LLM
    if deterministic.get("waiting_period_violated"):
        coverage_result = CoverageResult(
            coverage_status="EXCLUDED",
            coverage_amount_estimate=0,
            exclusions_triggered=[deterministic["waiting_period_reason"]],
            policy_sections_cited=["Section 5.3"],
            deterministic_deductions=deterministic,
            notes=f"Deterministic exclusion: {deterministic['waiting_period_reason']}",
        )
        claim_state.update({"coverage": coverage_result.model_dump()})
        return claim_state

    # --- Step 2: Semantic Pipeline (fuzzy exclusion check) ---
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
        coverage_result = CoverageResult(
            coverage_status="NEEDS_REVIEW",
            coverage_amount_estimate=0,
            exclusions_triggered=["RAG_CONFIDENCE_LOW"],
            rag_similarity_score=round(retrieval['max_similarity'], 3),
            deterministic_deductions=deterministic,
            notes=f"Hallucination guard triggered: Similarity {round(retrieval['max_similarity'], 3)} < {SIMILARITY_THRESHOLD}. Sent for manual review.",
        )
        claim_state.update({"coverage": coverage_result.model_dump()})
        try:
            mlflow.log_metric(f"{claim_id}_max_rag_similarity", retrieval["max_similarity"])
            mlflow.log_param(f"{claim_id}_coverage_status", "NEEDS_REVIEW (RAG_CONFIDENCE_LOW)")
        except:
            pass
        return claim_state
    
    policy_text = retrieval["text"]
    
    # LLM is ONLY used for fuzzy exclusion checking — all math is already done deterministically
    prompt = f"""
    You are an AI Coverage Eligibility Agent. Your role is LIMITED to checking for EXCLUSIONS
    that cannot be determined by structured rules alone (e.g., "cosmetic surgery unless due
    to an accident", "unproven experimental treatments").
    
    Do NOT compute copays, room rent caps, sub-limits, or waiting periods — those are handled
    by deterministic logic separately.
    
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
    - exclusions_triggered (list of strings — only fuzzy exclusions found in the policy text)
    - policy_sections_cited (list of section IDs that justify your determination)
    - notes (string explaining your reasoning)
    Do NOT output anything except valid JSON.
    """
    
    response_text = llm.generate(prompt, max_tokens=400)
    
    llm_result = {
        "coverage_status": "NEEDS_REVIEW",
        "exclusions_triggered": [],
        "policy_sections_cited": [],
        "notes": "Failed to parse LLM response"
    }
    
    try:
        start_idx = response_text.find("{")
        end_idx = response_text.rfind("}") + 1
        if start_idx != -1 and end_idx != -1:
            llm_result = json.loads(response_text[start_idx:end_idx])
    except Exception as e:
        print(f"[Agent 3] JSON parse error: {e}")

    # Merge deterministic and semantic results
    # If LLM found an exclusion, that takes priority
    final_status = llm_result.get("coverage_status", "NEEDS_REVIEW")

    # Compute estimated coverage amount after deterministic deductions
    claimed = extracted.get("claimed_amount", 0) or 0
    deduction = deterministic.get("total_deterministic_deduction", 0)
    estimated = max(0, claimed - deduction)

    # Apply sub-limit cap if triggered
    if deterministic.get("sub_limit_triggered") and deterministic.get("sub_limit_cap"):
        estimated = min(estimated, deterministic["sub_limit_cap"])

    coverage_result = CoverageResult(
        coverage_status=final_status,
        coverage_amount_estimate=estimated,
        exclusions_triggered=llm_result.get("exclusions_triggered", []),
        policy_sections_cited=llm_result.get("policy_sections_cited", []),
        rag_similarity_score=round(retrieval['max_similarity'], 3),
        deterministic_deductions=deterministic,
        notes=llm_result.get("notes", ""),
    )
    
    try:
        mlflow.log_metric(f"{claim_id}_max_rag_similarity", retrieval["max_similarity"])
        mlflow.log_param(f"{claim_id}_coverage_status", coverage_result.coverage_status)
        mlflow.log_metric(f"{claim_id}_coverage_amount_estimate", coverage_result.coverage_amount_estimate)
    except Exception as e:
        print(f"[Agent 3] MLflow log error: {e}")
        
    claim_state.update({"coverage": coverage_result.model_dump()})
    return claim_state
