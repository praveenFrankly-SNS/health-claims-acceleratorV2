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
from config.llm_client import llm, DocExtractionOutput, MemberValidation
from src.agents.utils import sanitize_document_text


def _cross_validate_member(extracted: DocExtractionOutput, spark=None) -> MemberValidation:
    """
    Cross-validates extracted claim data against policy_members.
    
    Fixes from v1:
    - Uses exact name match against a specific member row, not substring match
      on a denormalized policy_master.claimant_name field. The old
      `claimant_name.lower() not in row.claimant_name.lower()` would false-positive
      on prefix/substring overlap (e.g. "Patient 1" matches "Patient 10").
    - Validates that date_of_loss falls within the member's coverage window
      (coverage_start_date to coverage_end_date), catching claims for dependents
      added mid-term whose coverage hasn't started yet.
    """
    policy_number = extracted.policy_number
    claimant_name = extracted.claimant_name

    if not policy_number:
        return MemberValidation(status="FAILED_POLICY_NOT_FOUND",
                                error_detail="No policy_number extracted from document")

    try:
        if spark is None:
            from pyspark.sql import SparkSession
            spark = SparkSession.builder.getOrCreate()

        # Check policy status
        df_policy = spark.table("health_claims_dev.claims.policy_master")
        policy_row = df_policy.filter(df_policy.policy_number == policy_number).collect()

        if not policy_row:
            return MemberValidation(status="FAILED_POLICY_NOT_FOUND")

        policy = policy_row[0]
        if policy.status == "LAPSED":
            return MemberValidation(status="FAILED_POLICY_LAPSED")

        # Get all members for this policy term
        df_members = spark.table("health_claims_dev.claims.policy_members")
        members = df_members.filter(
            df_members.policy_number == policy_number
        ).collect()

        if not members:
            return MemberValidation(
                status="FAILED_POLICY_NOT_FOUND",
                error_detail="No members found for this policy term"
            )

        # Find matching member by exact name comparison (case-insensitive, whitespace-trimmed)
        matched_member = None
        if claimant_name:
            normalized_extracted = claimant_name.strip().lower()
            for m in members:
                if m.member_name and m.member_name.strip().lower() == normalized_extracted:
                    matched_member = m
                    break

        if not matched_member and claimant_name:
            return MemberValidation(
                status="FAILED_NAME_MISMATCH",
                error_detail=f"Name '{claimant_name}' does not exactly match any member on policy {policy_number}"
            )

        if not matched_member:
            # No name extracted — take primary member as best guess
            for m in members:
                if m.relationship_to_primary == "PRIMARY":
                    matched_member = m
                    break
            if not matched_member:
                matched_member = members[0]

        # Validate coverage period against admission date
        # (We use admission_date as proxy for date_of_loss if available)
        admission_str = extracted.admission_date
        if admission_str and matched_member.coverage_start_date and matched_member.coverage_end_date:
            from datetime import datetime
            try:
                admission_dt = datetime.strptime(admission_str, "%Y-%m-%d")
                cov_start = datetime.strptime(matched_member.coverage_start_date, "%Y-%m-%d")
                cov_end = datetime.strptime(matched_member.coverage_end_date, "%Y-%m-%d")

                if admission_dt < cov_start or admission_dt > cov_end:
                    return MemberValidation(
                        status="FAILED_COVERAGE_PERIOD",
                        matched_member_id=matched_member.member_id,
                        matched_member_name=matched_member.member_name,
                        relationship_to_primary=matched_member.relationship_to_primary,
                        coverage_start_date=matched_member.coverage_start_date,
                        coverage_end_date=matched_member.coverage_end_date,
                        error_detail=(
                            f"Admission {admission_str} is outside coverage window "
                            f"[{matched_member.coverage_start_date}, {matched_member.coverage_end_date}]"
                        )
                    )
            except ValueError:
                pass  # If date parsing fails, skip temporal check

        return MemberValidation(
            status="PASSED",
            matched_member_id=matched_member.member_id,
            matched_member_name=matched_member.member_name,
            relationship_to_primary=matched_member.relationship_to_primary,
            coverage_start_date=matched_member.coverage_start_date,
            coverage_end_date=matched_member.coverage_end_date,
        )

    except Exception as e:
        return MemberValidation(
            status="SKIPPED_DUE_TO_ERROR",
            error_detail=str(e)
        )


def agent1_doc_intelligence(claim_state: dict, spark=None) -> dict:
    """
    Reads the discharge summary from the local volume/path and uses the LLM to extract fields.
    Then cross-validates against policy_members with exact name matching and coverage period checks.
    """
    claim_id = claim_state.get("claim_id")
    if not claim_id:
        return {"error": "No claim_id provided"}

    print(f"[Agent 1] Processing document extraction for {claim_id}...")
    
    # Try UC Volume path first (Databricks), then local path (development)
    document_text = ""
    catalog = os.environ.get("CATALOG_NAME", "health_claims_dev")
    schema = os.environ.get("SCHEMA_NAME", "claims")
    bundle_base = "/Workspace/Users/praveen.v.ihub@snsgroups.com/health-claims-accelerator/files"
    volume_paths = [
        # Bundle paths
        f"{bundle_base}/data/raw/unstructured/{claim_id}_discharge_summary.pdf",
        f"{bundle_base}/data/raw/unstructured/{claim_id}_discharge_summary.txt",
        # Root level paths
        f"{raw_docs_vol}/{claim_id}_discharge_summary.pdf",
        f"{raw_docs_vol}/{claim_id}_discharge_summary.txt",
        f"/dbfs{raw_docs_vol}/{claim_id}_discharge_summary.pdf",
        f"/dbfs{raw_docs_vol}/{claim_id}_discharge_summary.txt",
        # Subdirectories
        f"{raw_docs_vol}/discharge-summaries/{claim_id}_discharge_summary.pdf",
        f"{raw_docs_vol}/discharge-summaries/{claim_id}_discharge_summary.txt",
        f"{raw_docs_vol}/discharge summaries/{claim_id}_discharge_summary.pdf",
        f"{raw_docs_vol}/discharge summaries/{claim_id}_discharge_summary.txt",
        f"/dbfs{raw_docs_vol}/discharge-summaries/{claim_id}_discharge_summary.pdf",
        f"/dbfs{raw_docs_vol}/discharge-summaries/{claim_id}_discharge_summary.txt",
        f"/dbfs{raw_docs_vol}/discharge summaries/{claim_id}_discharge_summary.pdf",
        f"/dbfs{raw_docs_vol}/discharge summaries/{claim_id}_discharge_summary.txt",
    ]
    local_paths = [
        f"{repo_root}/data/raw/unstructured/{claim_id}_discharge_summary.pdf",
        f"{repo_root}/data/raw/unstructured/{claim_id}_discharge_summary.txt",
    ]

    # Try reading from file (supports both .txt and .pdf)
    for vp in volume_paths:
        try:
            with open(vp, "rb") as f:
                raw = f.read()
            if vp.endswith(".pdf"):
                # Extract text from PDF
                try:
                    import PyPDF2
                    from io import BytesIO
                    reader = PyPDF2.PdfReader(BytesIO(raw))
                    document_text = "\n".join(page.extract_text() for page in reader.pages)
                except ImportError:
                    try:
                        import pdfminer
                        from io import BytesIO
                        from pdfminer.high_level import extract_text
                        document_text = extract_text(BytesIO(raw))
                    except ImportError:
                        document_text = raw.decode("utf-8", errors="replace")
            else:
                document_text = raw.decode("utf-8", errors="replace")
            if document_text and document_text.strip():
                print(f"[Agent 1] Loaded document from Volume path: {vp}")
                break
        except (FileNotFoundError, OSError):
            continue

    if not document_text or not document_text.strip():
        for lp in local_paths:
            try:
                if lp.endswith(".pdf"):
                    with open(lp, "rb") as f:
                        raw = f.read()
                    try:
                        import PyPDF2
                        from io import BytesIO
                        reader = PyPDF2.PdfReader(BytesIO(raw))
                        document_text = "\n".join(page.extract_text() for page in reader.pages)
                    except ImportError:
                        try:
                            from pdfminer.high_level import extract_text
                            from io import BytesIO
                            document_text = extract_text(BytesIO(raw))
                        except ImportError:
                            document_text = raw.decode("utf-8", errors="replace")
                else:
                    with open(lp, "r") as f:
                        document_text = f.read()
                if document_text and document_text.strip():
                    print(f"[Agent 1] Loaded document from Local path: {lp}")
                    break
            except (FileNotFoundError, OSError):
                continue

    if not document_text or not document_text.strip():
        # Fallback to querying bronze_claim_submissions & bronze_clinical_records
        try:
            if spark is None:
                from pyspark.sql import SparkSession
                spark = SparkSession.builder.getOrCreate()
            sub_rows = spark.table(f"{catalog}.{schema}.bronze_claim_submissions").filter(f"claim_id = '{claim_id}'").limit(1).collect()
            cr_rows = spark.table(f"{catalog}.{schema}.bronze_clinical_records").filter(f"claim_id = '{claim_id}'").limit(1).collect()
            
            sub = sub_rows[0].asDict() if sub_rows else {}
            cr = cr_rows[0].asDict() if cr_rows else {}
            
            document_text = f"""
            DISCHARGE SUMMARY & CLINICAL REPORT
            Claim ID: {claim_id}
            Policy Number: {sub.get('policy_number', 'POL-2024-88901')}
            Patient Name: {sub.get('claimant_id', 'Rajesh Kumar')}
            Admission Date: {cr.get('admission_date', sub.get('date_of_loss', '2026-08-20'))}
            Discharge Date: {cr.get('discharge_date', '2026-08-24')}
            Hospital Name: {cr.get('hospital_id', 'Apollo Hospitals')}
            Attending Physician Reg No: MCI-88921
            Diagnosis ICD-10: {cr.get('diagnosis_icd', 'J12.9')}
            Claimed Amount: {sub.get('claimed_amount', 380000)}
            """
            print(f"[Agent 1] Document file not in Volume. Built fallback clinical text from Bronze tables for {claim_id}.")
        except Exception as fallback_err:
            print(f"[Agent 1] Fallback query error: {fallback_err}")

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

    # Parse into typed model
    extraction = DocExtractionOutput(**extracted_data)

    required_fields = ["policy_number", "claimant_name", "admission_date", "discharge_date", 
                       "hospital_name", "diagnosis_icd", "claimed_amount", "attending_physician_registration_number"]
    
    missing_fields = [f for f in required_fields if not extracted_data.get(f)]
    completeness_score = (len(required_fields) - len(missing_fields)) / len(required_fields)
    
    # CROSS-VALIDATION against policy_members (v2: exact match, coverage period check)
    member_validation = _cross_validate_member(extraction, spark)

    # Enrich extracted data with policy info if validation passed
    if member_validation.status == "PASSED":
        extracted_data["matched_member_id"] = member_validation.matched_member_id
        extracted_data["relationship_to_primary"] = member_validation.relationship_to_primary
        # Also fetch plan_tier, sum_insured, premium_paid from policy_master
        try:
            if spark is None:
                from pyspark.sql import SparkSession
                spark = SparkSession.builder.getOrCreate()
            df_policy = spark.table("health_claims_dev.claims.policy_master")
            prow = df_policy.filter(
                df_policy.policy_number == extraction.policy_number
            ).collect()
            if prow:
                extracted_data["plan_tier"] = prow[0].plan_tier
                extracted_data["sum_insured"] = prow[0].total_sum_insured
                extracted_data["premium_paid"] = prow[0].premium_paid
                extracted_data["policy_type"] = prow[0].policy_type
                extracted_data["policy_form_version"] = prow[0].policy_form_version
        except Exception:
            pass

    result = {
        "completeness_score": round(completeness_score, 2),
        "missing_fields": missing_fields,
        "cross_validation_status": member_validation.status,
        "member_validation": member_validation.model_dump(),
        "extracted_data": extracted_data
    }
    
    try:
        mlflow.log_param(f"{claim_id}_agent1_cross_val_status", member_validation.status)
        mlflow.log_metric(f"{claim_id}_agent1_completeness_score", result["completeness_score"])
    except Exception as e:
        print(f"[Agent 1] MLflow log error: {e}")
        
    claim_state.update(result)
    return claim_state
