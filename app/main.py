import os
import sys
import json
import asyncio
import pandas as pd
from datetime import datetime
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

# Ensure repository root is in python path
app_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(app_dir, ".."))

# Add both app_dir (contains src/ and config/ copies) and repo_root to sys.path
for p in [app_dir, repo_root]:
    if p not in sys.path:
        sys.path.insert(0, p)

# Load environment variables from .env in repository root
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(repo_root, ".env"))
except ImportError:
    pass

app = FastAPI(title="Health Claims Accelerator API")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Target Unity Catalog database configuration
catalog = os.environ.get("CATALOG_NAME", "health_claims_dev")
schema = os.environ.get("SCHEMA_NAME", "claims")
audit_schema = "audit"

# Initialize Spark Session (Databricks Connect or Local Fallback)
spark = None
try:
    from databricks.connect import DatabricksSession
    cluster_id = os.environ.get("DATABRICKS_CLUSTER_ID")
    builder = DatabricksSession.builder
    if cluster_id:
        builder = builder.clusterId(cluster_id)
    else:
        builder = builder.serverless()
    spark = builder.getOrCreate()
    print("✓ Successfully initialized DatabricksSession")
except Exception as e:
    print(f"Notice: Databricks Connect could not initialize: {e}")
    try:
        from pyspark.sql import SparkSession
        spark = SparkSession.builder.getOrCreate()
        print("✓ Initialized local SparkSession fallback")
    except Exception as local_e:
        print(f"Error: Local Spark Session initialization failed: {local_e}")

# Note: Do not USE catalog.schema at startup — tables are referenced with fully-qualified names

# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------
class AdjudicationRequest(BaseModel):
    claim_id: str

class DecisionRequest(BaseModel):
    claim_id: str
    decision: str  # APPROVED, DENIED, INVESTIGATE
    reason: str

# ---------------------------------------------------------------------------
# Database & Ingest Helpers
# ---------------------------------------------------------------------------
def save_gold_decision(claim_id: str, claim_state: dict):
    if not spark:
        return
    from pyspark.sql import Row
    rows = [Row(claim_id=claim_id, payload=json.dumps(claim_state))]
    df_gold_new = spark.createDataFrame(rows)
    df_gold_new.createOrReplaceTempView("tmp_gold")
    gold_full_name = f"{catalog}.{schema}.gold_claim_decisions"
    
    if spark.catalog.tableExists(gold_full_name):
        spark.sql(f"""
            MERGE INTO {gold_full_name} t
            USING tmp_gold s
            ON t.claim_id = s.claim_id
            WHEN MATCHED THEN UPDATE SET *
            WHEN NOT MATCHED THEN INSERT *
        """)
    else:
        df_gold_new.write.format("delta").saveAsTable(gold_full_name)
        spark.sql(f"ALTER TABLE {gold_full_name} SET TBLPROPERTIES ('sensitivity'='PHI', 'classification'='restricted')")

def ingest_new_claim_from_supabase(claim_id: str):
    import requests
    import urllib.request
    
    supabase_url = os.environ.get("SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    
    if not supabase_url or not supabase_key:
        raise ValueError("Supabase credentials not configured in environment variables.")
        
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}"
    }
    
    # 1. Fetch claim submission
    res = requests.get(f"{supabase_url}/rest/v1/claim_submissions?claim_id=eq.{claim_id}", headers=headers)
    if res.status_code != 200 or not res.json():
        raise ValueError(f"Claim submissions for ID {claim_id} not found in Supabase (HTTP {res.status_code}).")
    claim_sub = res.json()[0]
    
    # Fetch clinical record
    res_clin = requests.get(f"{supabase_url}/rest/v1/clinical_records?claim_id=eq.{claim_id}", headers=headers)
    clin_rec = res_clin.json()[0] if res_clin.status_code == 200 and res_clin.json() else None
    
    # Fetch bills
    res_bills = requests.get(f"{supabase_url}/rest/v1/claim_bills?claim_id=eq.{claim_id}", headers=headers)
    bills = res_bills.json() if res_bills.status_code == 200 else []
    
    # 2. Append to Bronze Tables using Spark
    claim_sub["claimed_amount"] = int(claim_sub.get("claimed_amount") or 0)
    claim_sub["is_fraud"] = int(claim_sub.get("is_fraud") or 0)
    
    df_sub_new = spark.createDataFrame([{
        "claim_id": claim_sub.get("claim_id"),
        "policy_number": claim_sub.get("policy_number"),
        "claimant_id": claim_sub.get("claimant_id"),
        "date_of_loss": claim_sub.get("date_of_loss"),
        "claimed_amount": claim_sub.get("claimed_amount"),
        "submission_date": claim_sub.get("submission_date"),
        "status": claim_sub.get("status"),
        "is_fraud": claim_sub.get("is_fraud"),
        "claim_form_metadata": claim_sub.get("claim_form_metadata")
    }])
    from pyspark.sql.functions import current_timestamp
    df_sub_new = df_sub_new.withColumn("ingested_at", current_timestamp())
    df_sub_new.write.format("delta").mode("append").saveAsTable(f"{catalog}.{schema}.bronze_claim_submissions")
    
    if clin_rec:
        clin_rec["record_seq"] = int(clin_rec.get("record_seq") or 1)
        df_clin_new = spark.createDataFrame([{
            "claim_id": clin_rec.get("claim_id"),
            "record_seq": clin_rec.get("record_seq"),
            "admission_date": clin_rec.get("admission_date"),
            "discharge_date": clin_rec.get("discharge_date"),
            "hospital_id": clin_rec.get("hospital_id"),
            "diagnosis_icd": clin_rec.get("diagnosis_icd"),
            "attending_physician_registration_number": clin_rec.get("attending_physician_registration_number")
        }])
        df_clin_new.write.format("delta").mode("append").saveAsTable(f"{catalog}.{schema}.clinical_records")
        
    if bills:
        bill_rows = []
        for b in bills:
            bill_rows.append({
                "claim_id": b.get("claim_id"),
                "bill_no": b.get("bill_no"),
                "bill_date": b.get("bill_date"),
                "raw_expense_label": b.get("raw_expense_label"),
                "normalized_expense_type": b.get("normalized_expense_type"),
                "amount": int(b.get("amount") or 0)
            })
        df_bills_new = spark.createDataFrame(bill_rows)
        df_bills_new.write.format("delta").mode("append").saveAsTable(f"{catalog}.{schema}.claim_bills")
        
    # 3. Download proof documents from Supabase Storage to Volume
    for file_type, bucket, prefix in [("discharge", "claim-discharges", "discharge-summaries"), ("bill", "claim-bills", "hospital-bills")]:
        volume_path = f"/Volumes/{catalog}/{schema}/raw_documents/{prefix}/"
        try:
            spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.{schema}.raw_documents")
        except:
            pass
            
        for ext in ["pdf", "txt", "png", "jpg", "jpeg"]:
            file_name = f"{claim_id}_{file_type}.{ext}"
            download_url = f"{supabase_url}/storage/v1/object/public/{bucket}/{prefix}/{file_name}"
            test_res = requests.head(download_url)
            if test_res.status_code == 200:
                try:
                    dest_file_path = os.path.join(volume_path, file_name)
                    os.makedirs(os.path.dirname(dest_file_path), exist_ok=True)
                    urllib.request.urlretrieve(download_url, dest_file_path)
                    print(f"✓ Downloaded {file_name} to Volume.")
                    break
                except Exception as doc_err:
                    print(f"Error copying {file_name} to volume: {doc_err}")
                    
    # 4. Compute Silver Features for this single claim ID
    from pyspark.sql.functions import sha2
    spark.sql(f"""
        MERGE INTO {catalog}.{schema}.silver_claims t
        USING (
            SELECT
                s.claim_id,
                s.policy_number,
                s.claimant_id,
                s.date_of_loss,
                s.claimed_amount,
                cast(datediff(to_date(s.date_of_loss), to_date(p.inception_date)) as int) as days_since_inception,
                cast((s.claimed_amount / p.premium_paid) as double) as amount_to_premium_ratio,
                0 as member_claim_velocity_90d,
                0 as policy_claim_velocity_90d,
                cast((p.total_sum_insured - s.claimed_amount) as double) as remaining_sum_insured_balance,
                0.05 as physician_fraud_ratio,
                cast(s.claimed_amount as double) as hospital_billing_velocity_30d,
                'NOT_SOUGHT' as pre_auth_category,
                0.0 as pre_auth_approval_ratio,
                0.0 as pct_bills_exceeding_structured_limits,
                'v2.0' as feature_pipeline_version,
                sha2(s.claimant_id, 256) as claimant_name_hash,
                current_timestamp() as ingested_at,
                0 as claim_velocity,
                0 as is_fraud
            FROM {catalog}.{schema}.bronze_claim_submissions s
            LEFT JOIN {catalog}.{schema}.policy_master p ON s.policy_number = p.policy_number
            WHERE s.claim_id = '{claim_id}'
        ) s
        ON t.claim_id = s.claim_id
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
    """)
    
    spark.sql(f"""
        MERGE INTO {catalog}.{schema}.silver_claim_features t
        USING (
            SELECT
                claim_id, policy_number, claimant_id, date_of_loss,
                claimed_amount, days_since_inception, amount_to_premium_ratio,
                member_claim_velocity_90d, policy_claim_velocity_90d,
                remaining_sum_insured_balance,
                physician_fraud_ratio, hospital_billing_velocity_30d,
                pre_auth_category, pre_auth_approval_ratio,
                pct_bills_exceeding_structured_limits,
                feature_pipeline_version, claimant_name_hash, ingested_at
            FROM {catalog}.{schema}.silver_claims
            WHERE claim_id = '{claim_id}'
        ) s
        ON t.claim_id = s.claim_id
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
    """)

# ---------------------------------------------------------------------------
# REST API Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/config/supabase")
def get_supabase_config():
    """Retrieve Supabase URL and Service Key for the Customer Portal."""
    return {
        "supabase_url": os.environ.get("SUPABASE_URL", ""),
        "supabase_key": os.environ.get("SUPABASE_SERVICE_KEY", "")
    }

@app.get("/api/claims")
def get_claims():
    """Retrieve claims in the queue from silver_claims or default fallback."""
    if not spark:
        return []
    try:
        silver_table = f"{catalog}.{schema}.silver_claims"
        if not spark.catalog.tableExists(silver_table):
            return []
        
        # Deduplicate by claim_id — bronze_claim_submissions uses append mode so
        # re-runs can produce duplicate silver rows. Always take the latest ingested_at.
        from pyspark.sql.window import Window
        from pyspark.sql.functions import row_number, desc, col

        w = Window.partitionBy("claim_id").orderBy(desc("ingested_at"))
        df_silver = (spark.table(silver_table)
                     .withColumn("_rn", row_number().over(w))
                     .filter(col("_rn") == 1)
                     .drop("_rn"))

        # Check if already processed in gold_claim_decisions
        gold_table = f"{catalog}.{schema}.gold_claim_decisions"
        processed_ids = set()
        
        if spark.catalog.tableExists(gold_table):
            df_gold = spark.table(gold_table).select("claim_id")
            df_pending = df_silver.join(df_gold, on="claim_id", how="left_anti").orderBy("claim_id").limit(100).toPandas()
            
            if len(df_pending) > 0:
                df = df_pending
            else:
                df = df_silver.orderBy("claim_id").limit(100).toPandas()
                
            df_gold_all = df_gold.toPandas()
            processed_ids = set(df_gold_all["claim_id"].tolist())
        else:
            df = df_silver.orderBy("claim_id").limit(100).toPandas()
            
        claims = []
        seen_ids = set()  # extra guard against any remaining dupes in pandas
        for _, row in df.iterrows():
            cid = row["claim_id"]
            if cid in seen_ids:
                continue
            seen_ids.add(cid)

            def safe_int(val, default=0):
                try:
                    if val is None or (isinstance(val, float) and (val != val)):
                        return default
                    return int(val)
                except (ValueError, TypeError):
                    return default

            def safe_float(val, default=0.0):
                try:
                    if val is None or (isinstance(val, float) and (val != val)):
                        return default
                    return float(val)
                except (ValueError, TypeError):
                    return default

            claims.append({
                "claim_id": cid,
                "policy_number": row.get("policy_number"),
                "claimant_id": row.get("claimant_id"),
                "date_of_loss": row.get("date_of_loss"),
                "claimed_amount": safe_int(row.get("claimed_amount"), 0),
                "days_since_inception": safe_int(row.get("days_since_inception"), 500),
                "claim_velocity": safe_int(row.get("claim_velocity"), 0),
                "amount_to_premium_ratio": safe_float(row.get("amount_to_premium_ratio"), 0.0),
                "status": "PROCESSED" if cid in processed_ids else "PENDING"
            })
        return claims
    except Exception as e:
        print(f"Error loading claims queue: {str(e)}")
        return []

@app.get("/api/claims/{claim_id}/details")
def get_claim_details(claim_id: str):
    """
    Returns full claim context for a given claim_id:
    - Claim submission info, clinical record, bills, policy info,
    - Gold decision payload (if already processed)
    - Document availability flags and failure reason explanation
    """
    if not spark:
        raise HTTPException(status_code=503, detail="Spark not available")

    result: dict = {}

    # --- Claim submission ---
    try:
        rows = spark.table(f"{catalog}.{schema}.bronze_claim_submissions") \
            .filter(f"claim_id = '{claim_id}'").limit(1).collect()
        if rows:
            r = rows[0].asDict()
            result["claim"] = {k: str(v) if v is not None else None
                               for k, v in r.items() if k not in ("source",)}
    except Exception as e:
        result["claim"] = {"error": str(e)}

    # --- Clinical record ---
    try:
        rows = spark.table(f"{catalog}.{schema}.bronze_clinical_records") \
            .filter(f"claim_id = '{claim_id}'").limit(1).collect()
        if rows:
            result["clinical"] = {k: str(v) if v is not None else None
                                  for k, v in rows[0].asDict().items() if k not in ("source",)}
    except Exception as e:
        result["clinical"] = {"error": str(e)}

    # --- Bills ---
    try:
        rows = spark.table(f"{catalog}.{schema}.bronze_claim_bills") \
            .filter(f"claim_id = '{claim_id}'").collect()
        result["bills"] = [{k: str(v) if v is not None else None
                            for k, v in r.asDict().items() if k not in ("source",)} for r in rows]
    except Exception as e:
        result["bills"] = []

    # --- Policy info + members ---
    try:
        sub_pn = (result.get("claim") or {}).get("policy_number")
        if sub_pn:
            rows = spark.table(f"{catalog}.{schema}.policy_master") \
                .filter(f"policy_number = '{sub_pn}'").limit(1).collect()
            if rows:
                result["policy"] = {k: str(v) if v is not None else None
                                    for k, v in rows[0].asDict().items()}
            mem_rows = spark.table(f"{catalog}.{schema}.policy_members") \
                .filter(f"policy_number = '{sub_pn}'").collect()
            result["policy_members"] = [{k: str(v) if v is not None else None
                                         for k, v in r.asDict().items()} for r in mem_rows]
    except Exception as e:
        result["policy"] = {"error": str(e)}
        result["policy_members"] = []

    # --- Gold decision (if exists) ---
    try:
        gold_table = f"{catalog}.{schema}.gold_claim_decisions"
        if spark.catalog.tableExists(gold_table):
            rows = spark.table(gold_table).filter(f"claim_id = '{claim_id}'").limit(1).collect()
            if rows:
                try:
                    result["gold_decision"] = json.loads(rows[0]["payload"])
                except Exception:
                    result["gold_decision"] = None
    except Exception:
        result["gold_decision"] = None

    # --- Document availability + discharge summary text ---
    # Try UC Volume first, then fall back to the deployed workspace bundle files
    # Note: on Databricks Apps, __file__ resolves to a /Workspace/ path.
    # os.path.exists() works on /Workspace/ paths in Databricks Runtime.
    # We also try the standard workspace bundle location as a fallback.
    bundle_base = "/Workspace/Users/praveen.v.ihub@snsgroups.com/.bundle/health-claims-accelerator/default/files"
    raw_docs_vol = os.environ.get("RAW_DOCUMENTS_VOLUME_PATH", f"/Volumes/{catalog}/{schema}/raw_documents")
    discharge_paths = [
        # UC Volume root
        f"{raw_docs_vol}/{claim_id}_discharge_summary.pdf",
        f"{raw_docs_vol}/{claim_id}_discharge_summary.txt",
        # UC Volume subdirectories — try both pdf and txt (new claims have pdf, old have txt)
        f"{raw_docs_vol}/discharge-summaries/{claim_id}_discharge_summary.pdf",
        f"{raw_docs_vol}/discharge-summaries/{claim_id}_discharge_summary.txt",
        f"{raw_docs_vol}/discharge summaries/{claim_id}_discharge_summary.pdf",
        f"{raw_docs_vol}/discharge summaries/{claim_id}_discharge_summary.txt",
        # Bundle workspace fallback
        f"{bundle_base}/data/raw/unstructured/{claim_id}_discharge_summary.txt",
        f"{bundle_base}/data/raw/unstructured/{claim_id}_discharge_summary.pdf",
        os.path.join(app_dir, "data", "raw", "unstructured", f"{claim_id}_discharge_summary.txt"),
        os.path.join(app_dir, "data", "raw", "unstructured", f"{claim_id}_discharge_summary.pdf"),
        os.path.join(repo_root, "data", "raw", "unstructured", f"{claim_id}_discharge_summary.txt"),
        os.path.join(repo_root, "data", "raw", "unstructured", f"{claim_id}_discharge_summary.pdf"),
    ]
    bill_paths = [
        # UC Volume paths
        f"{raw_docs_vol}/{claim_id}_hospital_bill.pdf",
        f"{raw_docs_vol}/{claim_id}_payment_receipt.jpg",
        f"{raw_docs_vol}/hospital-bills/{claim_id}_hospital_bill.pdf",
        f"{raw_docs_vol}/hospital-bills/{claim_id}_payment_receipt.jpg",
        f"{raw_docs_vol}/hospital bills/{claim_id}_hospital_bill.pdf",
        f"{raw_docs_vol}/hospital bills/{claim_id}_payment_receipt.jpg",
        # Local container fallbacks
        os.path.join(app_dir, "data", "raw", "bills", f"{claim_id}_hospital_bill.pdf"),
        os.path.join(app_dir, "data", "raw", "bills", f"{claim_id}_payment_receipt.jpg"),
        os.path.join(repo_root, "data", "raw", "bills", f"{claim_id}_hospital_bill.pdf"),
        os.path.join(repo_root, "data", "raw", "bills", f"{claim_id}_payment_receipt.jpg"),
    ]

    discharge_text = None
    discharge_found_path = None
    for p in discharge_paths:
        try:
            # Try open() directly — don't rely on os.path.exists() 
            # UC Volume subdirectory may not appear to os.path.exists() but files are still readable
            if p.endswith(".txt"):
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    discharge_text = f.read()
                if discharge_text.strip():
                    discharge_found_path = p
                    break
            elif p.endswith(".pdf"):
                with open(p, "rb") as f:
                    raw = f.read()
                try:
                    import pypdf
                    from io import BytesIO
                    reader = pypdf.PdfReader(BytesIO(raw))
                    discharge_text = "\n".join(pg.extract_text() or "" for pg in reader.pages)
                except Exception:
                    try:
                        import PyPDF2
                        from io import BytesIO
                        reader = PyPDF2.PdfReader(BytesIO(raw))
                        discharge_text = "\n".join(pg.extract_text() or "" for pg in reader.pages)
                    except Exception:
                        discharge_text = f"[PDF found: {p}]"
                discharge_found_path = p
                break
        except (FileNotFoundError, OSError):
            continue
        except Exception:
            continue

    # Check hospital bill — try open() directly, same as discharge (os.path.exists fails on UC Volume subdirs)
    hospital_bill_available = False
    for p in bill_paths:
        try:
            with open(p, "rb") as f:
                _ = f.read(1)  # just check it's readable
            hospital_bill_available = True
            break
        except (FileNotFoundError, OSError):
            continue
        except Exception:
            continue

    result["documents"] = {
        "discharge_summary_available": discharge_text is not None,
        "discharge_summary_text": discharge_text,
        "discharge_found_path": discharge_found_path,
        "hospital_bill_available": hospital_bill_available,
    }

    # --- Why it failed ---
    failure_reason = None
    gd = result.get("gold_decision")
    if gd:
        status = gd.get("pipeline_status", "")
        if status == "HALTED_INCOMPLETE":
            member_val = gd.get("member_validation", {}) or {}
            extracted = gd.get("extracted_data", {}) or {}
            failure_reason = {
                "status": "HALTED_INCOMPLETE",
                "cross_validation_status": gd.get("cross_validation_status", "UNKNOWN"),
                "member_validation_status": member_val.get("status", "UNKNOWN"),
                "error_detail": member_val.get("error_detail") or extracted.get(
                    "cross_validation_error",
                    "Document extraction returned 0% completeness. Discharge summary not found in volume or LLM extraction failed."
                ),
                "completeness_score": gd.get("completeness_score", 0),
                "missing_fields": gd.get("missing_fields", []),
            }
    else:
        if not result["documents"]["discharge_summary_available"]:
            vol_dir = "discharge summaries" if os.path.exists(f"/Volumes/{catalog}/{schema}/raw_documents/discharge summaries") else "discharge-summaries"
            failure_reason = {
                "status": "DOCS_MISSING",
                "error_detail": (
                    f"Discharge summary not found in UC Volume folder: '{vol_dir}'. "
                    "Please run the Bronze Ingestion Job in Databricks (or 01_bronze_ingestion.py) to sync files from Supabase Storage into the Volume."
                ),
            }
    result["failure_reason"] = failure_reason

    return result


@app.get("/api/debug/paths")
def debug_paths():
    """Debug endpoint — shows resolved paths and which discharge summary files exist."""
    bundle_base = "/Workspace/Users/praveen.v.ihub@snsgroups.com/.bundle/health-claims-accelerator/default/files"
    
    # Test with a current inference claim ID
    test_claim = "CLM-2026-00433"
    raw_docs_vol = os.environ.get("RAW_DOCUMENTS_VOLUME_PATH", f"/Volumes/{catalog}/{schema}/raw_documents")
    vol_discharge_hyphen = f"{raw_docs_vol}/discharge-summaries"
    vol_discharge_space = f"{raw_docs_vol}/discharge summaries"
    
    paths_to_check = {
        "pdf_in_volume_root": f"{raw_docs_vol}/{test_claim}_discharge_summary.pdf",
        "txt_in_volume_root": f"{raw_docs_vol}/{test_claim}_discharge_summary.txt",
        "pdf_in_volume_hyphen": f"{vol_discharge_hyphen}/{test_claim}_discharge_summary.pdf",
        "txt_in_volume_hyphen": f"{vol_discharge_hyphen}/{test_claim}_discharge_summary.txt",
        "pdf_in_volume_space": f"{vol_discharge_space}/{test_claim}_discharge_summary.pdf",
        "txt_in_volume_space": f"{vol_discharge_space}/{test_claim}_discharge_summary.txt",
        "bundle_txt": f"{bundle_base}/data/raw/unstructured/{test_claim}_discharge_summary.txt",
    }
    
    # Also list what's actually in the volume directory
    volume_files = []
    vol_discharge = raw_docs_vol
    try:
        if os.path.exists(raw_docs_vol):
            all_files = os.listdir(raw_docs_vol)
            volume_files = sorted(all_files)
        else:
            volume_files = [f"DIRECTORY DOES NOT EXIST: {raw_docs_vol}"]
    except Exception as e:
        volume_files = [f"ERROR listing directory: {e}"]
    
    return {
        "app_dir": app_dir,
        "repo_root": repo_root,
        "cwd": os.getcwd(),
        "catalog": catalog,
        "schema": schema,
        "test_claim": test_claim,
        "path_exists": {k: os.path.exists(v) for k, v in paths_to_check.items()},
        "paths_checked": paths_to_check,
        "volume_discharge_dir": vol_discharge,
        "volume_dir_exists": os.path.exists(vol_discharge),
        "files_in_volume": volume_files[:30],  # first 30 files
        "total_files_in_volume": len(volume_files),
    }


@app.post("/api/decide")
def submit_decision(req: DecisionRequest):
    """Record a human adjuster decision in the audit decisions table."""
    if not spark:
        raise HTTPException(status_code=503, detail="Spark Session not active")
    try:
        audit_table = f"{catalog}.{audit_schema}.adjuster_decisions"
        spark.sql(f"""
            INSERT INTO {audit_table} (claim_id, action, reason, user, timestamp)
            VALUES ('{req.claim_id}', '{req.decision}', '{req.reason.replace("'", "''")}', 'Adjuster', current_timestamp())
        """)
        return {"status": "SUCCESS", "message": f"Decision recorded for claim {req.claim_id}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to record decision: {str(e)}")

@app.get("/api/review/queue")
def get_review_queue():
    """Retrieve claims assigned to human review based on dashboard view."""
    if not spark:
        return []
    try:
        # Load dashboard view
        dash_view = f"{catalog}.{schema}.vw_claims_dashboard"
        if spark.catalog.tableExists(dash_view):
            df = spark.table(dash_view).toPandas()
            return df.to_dict(orient="records")
        return []
    except Exception as e:
        print(f"Error querying dashboard view: {e}")
        return []

@app.get("/api/review/audit")
def get_audit_trail():
    """Retrieve human decision audits."""
    if not spark:
        return []
    try:
        audit_table = f"{catalog}.{audit_schema}.adjuster_decisions"
        if spark.catalog.tableExists(audit_table):
            df = spark.table(audit_table).orderBy(col("timestamp").desc()).limit(30).toPandas()
            return df.to_dict(orient="records")
        return []
    except Exception as e:
        print(f"Error loading audit trail: {e}")
        return []

@app.get("/api/explorer")
def get_gold_explorer():
    """Retrieve processed decision JSONs for inspection."""
    if not spark:
        return []
    try:
        gold_table = f"{catalog}.{schema}.gold_claim_decisions"
        if not spark.catalog.tableExists(gold_table):
            return []
        
        df = spark.table(gold_table).orderBy("claim_id").toPandas()
        results = []
        for _, row in df.iterrows():
            cid = row["claim_id"]
            try:
                payload = json.loads(row["payload"])
            except:
                payload = {"error": "Invalid payload format"}
            results.append({
                "claim_id": cid,
                "pipeline_status": payload.get("pipeline_status", "UNKNOWN"),
                "coverage_status": payload.get("coverage", {}).get("coverage_status", "UNKNOWN"),
                "fraud_score": payload.get("fraud", {}).get("fraud_score", 0.0),
                "adjuster_allocation": payload.get("adjuster_allocation", "N/A"),
                "payload": payload
            })
        return results
    except Exception as e:
        print(f"Error loading gold explorer: {str(e)}")
        return []

@app.get("/api/analytics")
def get_analytics():
    """Calculate executive business metrics."""
    if not spark:
        return {"total_processed": 0, "auto_adjudication_rate": "0%", "avg_processing_time": "0s", "total_reserve": 0}
    try:
        dash_view = f"{catalog}.{schema}.vw_claims_dashboard"
        if not spark.catalog.tableExists(dash_view):
            return {"total_processed": 0, "auto_adjudication_rate": "0%", "avg_processing_time": "0s", "total_reserve": 0}
            
        df = spark.table(dash_view).toPandas()
        total_processed = len(df)
        if total_processed == 0:
            return {"total_processed": 0, "auto_adjudication_rate": "0%", "avg_processing_time": "4.2s", "total_reserve": 0}
            
        auto_approved = len(df[df["assigned_adjuster"] == "AUTO_APPROVED"])
        total_reserve = float(df["reserve_amount"].astype(float).sum())
        
        return {
            "total_processed": total_processed,
            "auto_adjudication_rate": f"{(auto_approved / total_processed) * 100:.1f}%",
            "avg_processing_time": "4.2s",
            "total_reserve": total_reserve
        }
    except Exception as e:
        print(f"Analytics error: {e}")
        return {"total_processed": 0, "auto_adjudication_rate": "0%", "avg_processing_time": "4.2s", "total_reserve": 0}

# ---------------------------------------------------------------------------
# SSE Agent Execution Stream
# ---------------------------------------------------------------------------

@app.get("/api/adjudicate/stream/{claim_id}")
async def stream_adjudication(claim_id: str):
    """Executes the multi-agent orchestration and streams step-by-step trace."""
    if not spark:
        raise HTTPException(status_code=503, detail="Spark Session not active")
        
    async def event_generator():
        # Step 0: State Hydration
        yield {
            "event": "message",
            "data": json.dumps({"agent": "setup", "status": "RUNNING", "message": f"Hydrating state for claim {claim_id}..."})
        }
        await asyncio.sleep(0.5)
        
        try:
            # Load static details from Spark
            sub_rows = spark.table(f"{catalog}.{schema}.bronze_claim_submissions").filter(f"claim_id = '{claim_id}'").collect()
            if not sub_rows:
                yield {
                    "event": "message",
                    "data": json.dumps({"agent": "setup", "status": "RUNNING", "message": f"Claim {claim_id} not in catalog. Ingesting from Supabase in real-time..."})
                }
                await asyncio.sleep(0.5)
                try:
                    ingest_new_claim_from_supabase(claim_id)
                    sub_rows = spark.table(f"{catalog}.{schema}.bronze_claim_submissions").filter(f"claim_id = '{claim_id}'").collect()
                except Exception as ingest_err:
                    raise ValueError(f"Real-time ingestion failed for claim {claim_id}: {ingest_err}")
                
                if not sub_rows:
                    raise ValueError("Claim submissions not found even after querying Supabase.")
                
                yield {
                    "event": "message",
                    "data": json.dumps({"agent": "setup", "status": "RUNNING", "message": f"✓ Ingestion complete. Hydrating state for claim {claim_id}..."})
                }
                await asyncio.sleep(0.5)
                
            claim_sub = sub_rows[0].asDict()
            
            # Load features
            features_rows = spark.table(f"{catalog}.{schema}.silver_claims").filter(f"claim_id = '{claim_id}'").collect()
            claim_features = features_rows[0].asDict() if features_rows else {}

            # Safe cast helpers — Spark Row values can be None even when key exists
            def _int(val, default=0):
                try:
                    return int(val) if val is not None and val == val else default
                except (TypeError, ValueError):
                    return default

            def _float(val, default=0.0):
                try:
                    return float(val) if val is not None and val == val else default
                except (TypeError, ValueError):
                    return default

            claim_state = {
                "claim_id": claim_id,
                "policy_number": claim_sub.get("policy_number"),
                "claimant_id": claim_sub.get("claimant_id"),
                "date_of_loss": claim_sub.get("date_of_loss"),
                "claimed_amount": _int(claim_sub.get("claimed_amount"), 0),
                "days_since_inception": _int(claim_features.get("days_since_inception"), 500),
                "claim_velocity": _int(claim_features.get("claim_velocity"), 0),
                "amount_to_premium_ratio": _float(claim_features.get("amount_to_premium_ratio"), 0.0),
                "pipeline_status": "RUNNING"
            }
            
            yield {
                "event": "message",
                "data": json.dumps({"agent": "setup", "status": "SUCCESS", "message": "State hydrated.", "state": claim_state})
            }
        except Exception as e:
            yield {
                "event": "message",
                "data": json.dumps({"agent": "setup", "status": "FAILED", "message": f"State hydration failed: {str(e)}"})
            }
            return
            
        await asyncio.sleep(0.5)
        
        # Step 1: Agent 1 - Document Intelligence
        yield {
            "event": "message",
            "data": json.dumps({"agent": "agent1_doc_intelligence", "status": "RUNNING", "message": "Agent 1: Extracting documents and cross-validating..."})
        }
        try:
            from src.agents.doc_intelligence import agent1_doc_intelligence
            claim_state = agent1_doc_intelligence(claim_state, spark=spark)
            
            yield {
                "event": "message",
                "data": json.dumps({
                    "agent": "agent1_doc_intelligence",
                    "status": "SUCCESS",
                    "message": "Verification complete.",
                    "data": {
                        "extracted_data": claim_state.get("extracted_data"),
                        "completeness_score": claim_state.get("completeness_score"),
                        "cross_validation_status": claim_state.get("cross_validation_status")
                    }
                })
            }
        except Exception as e:
            yield {
                "event": "message",
                "data": json.dumps({"agent": "agent1_doc_intelligence", "status": "FAILED", "message": f"Agent 1 failed: {str(e)}"})
            }
            return
            
        await asyncio.sleep(0.5)
        
        # Check validation halt
        if claim_state.get("cross_validation_status") != "PASSED":
            claim_state["pipeline_status"] = "HALTED_INCOMPLETE"
            save_gold_decision(claim_id, claim_state)
            yield {
                "event": "message",
                "data": json.dumps({"agent": "halt", "status": "HALTED", "message": "Pipeline halted due to validation failure."})
            }
            return
            
        # Step 2: Agent 2 - Fraud Detection
        yield {
            "event": "message",
            "data": json.dumps({"agent": "agent2_fraud", "status": "RUNNING", "message": "Agent 2: Scoring fraud & checking narrative anomalies..."})
        }
        try:
            from src.agents.fraud import agent2_fraud
            claim_state = agent2_fraud(claim_state, spark=spark)
            yield {
                "event": "message",
                "data": json.dumps({
                    "agent": "agent2_fraud",
                    "status": "SUCCESS",
                    "message": "Fraud checking completed.",
                    "data": claim_state.get("fraud")
                })
            }
        except Exception as e:
            yield {
                "event": "message",
                "data": json.dumps({"agent": "agent2_fraud", "status": "FAILED", "message": f"Agent 2 failed: {str(e)}"})
            }
            return
            
        await asyncio.sleep(0.5)
        
        # Step 3: Agent 3 - Coverage Verification
        yield {
            "event": "message",
            "data": json.dumps({"agent": "agent3_coverage", "status": "RUNNING", "message": "Agent 3: Verifying policy exclusions and copays..."})
        }
        try:
            from src.agents.coverage import agent3_coverage
            claim_state = agent3_coverage(claim_state)
            yield {
                "event": "message",
                "data": json.dumps({
                    "agent": "agent3_coverage",
                    "status": "SUCCESS",
                    "message": "Exclusion parsing complete.",
                    "data": claim_state.get("coverage")
                })
            }
        except Exception as e:
            yield {
                "event": "message",
                "data": json.dumps({"agent": "agent3_coverage", "status": "FAILED", "message": f"Agent 3 failed: {str(e)}"})
            }
            return
            
        await asyncio.sleep(0.5)
        
        # Step 4: Agent 4 - Reserve Estimation
        yield {
            "event": "message",
            "data": json.dumps({"agent": "agent4_reserve", "status": "RUNNING", "message": "Agent 4: Calculating severity and reserving quantile intervals..."})
        }
        try:
            from src.agents.reserve import agent4_reserve
            claim_state = agent4_reserve(claim_state, spark=spark)
            yield {
                "event": "message",
                "data": json.dumps({
                    "agent": "agent4_reserve",
                    "status": "SUCCESS",
                    "message": "Reserve calculated.",
                    "data": claim_state.get("reserve")
                })
            }
        except Exception as e:
            yield {
                "event": "message",
                "data": json.dumps({"agent": "agent4_reserve", "status": "FAILED", "message": f"Agent 4 failed: {str(e)}"})
            }
            return
            
        await asyncio.sleep(0.5)
        
        # Step 5: Adjuster Allocation
        yield {
            "event": "message",
            "data": json.dumps({"agent": "adjuster_allocation", "status": "RUNNING", "message": "Routing claim adjuster..."})
        }
        try:
            from src.agents.adjuster_allocation import allocate_adjuster
            claim_state = allocate_adjuster(claim_state)
            claim_state["pipeline_status"] = "COMPLETED"
            yield {
                "event": "message",
                "data": json.dumps({
                    "agent": "adjuster_allocation",
                    "status": "SUCCESS",
                    "message": f"Assigned to {claim_state.get('adjuster_allocation')}",
                    "data": {"adjuster_allocation": claim_state.get("adjuster_allocation")}
                })
            }
        except Exception as e:
            yield {
                "event": "message",
                "data": json.dumps({"agent": "adjuster_allocation", "status": "FAILED", "message": f"Routing failed: {str(e)}"})
            }
            return
            
        await asyncio.sleep(0.5)
        
        # Step 6: Materialize Gold Decision
        yield {
            "event": "message",
            "data": json.dumps({"agent": "save", "status": "RUNNING", "message": "Saving results to Delta Lake..."})
        }
        try:
            save_gold_decision(claim_id, claim_state)
            yield {
                "event": "message",
                "data": json.dumps({"agent": "save", "status": "SUCCESS", "message": "Materials saved!"})
            }
        except Exception as e:
            yield {
                "event": "message",
                "data": json.dumps({"agent": "save", "status": "FAILED", "message": f"Save failed: {str(e)}"})
            }
            
    return EventSourceResponse(event_generator())


@app.get("/api/debug/reset_gold")
def reset_gold_endpoint():
    """Truncates the gold decisions table to bring back all claims into the pending queue."""
    if not spark:
        return {"error": "Spark not available"}
    try:
        table_name = f"{catalog}.{schema}.gold_claim_decisions"
        spark.sql(f"TRUNCATE TABLE {table_name}")
        return {"status": "SUCCESS", "message": f"Table {table_name} truncated successfully!"}
    except Exception as e:
        # Fallback to drop if truncate fails
        try:
            spark.sql(f"DROP TABLE IF EXISTS {table_name}")
            return {"status": "SUCCESS", "message": f"Table {table_name} dropped successfully!"}
        except Exception as e2:
            return {"status": "FAILED", "error": str(e), "drop_error": str(e2)}


@app.get("/api/debug/list_volume")
def debug_list_volume():
    """Endpoint to inspect what volume directories and files are visible to the FastAPI container."""
    try:
        vol_path = os.environ.get("RAW_DOCUMENTS_VOLUME_PATH", f"/Volumes/{catalog}/{schema}/raw_documents")
        res = {
            "vol_path_env_var": os.environ.get("RAW_DOCUMENTS_VOLUME_PATH"),
            "vol_path": vol_path,
            "exists": os.path.exists(vol_path),
            "is_dir": os.path.isdir(vol_path) if os.path.exists(vol_path) else False,
        }
        if os.path.exists(vol_path):
            res["contents"] = os.listdir(vol_path)
            # Try listing subdirectories
            subdirs = {}
            for item in os.listdir(vol_path):
                item_path = os.path.join(vol_path, item)
                if os.path.isdir(item_path):
                    try:
                        subdirs[item] = os.listdir(item_path)[:30] # list first 30 files
                    except Exception as sub_e:
                        subdirs[item] = f"Error listing: {sub_e}"
            res["subdirs"] = subdirs
        return res
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Static Assets Serving
# ---------------------------------------------------------------------------
# Mount React static files (only if the directory exists - for production build deployment)
frontend_dist = os.path.join(app_dir, "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
else:
    @app.get("/")
    def index_fallback():
        return {"message": "API active. Frontend React static build not found. Run dev server locally."}
