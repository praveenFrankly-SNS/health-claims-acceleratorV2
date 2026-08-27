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
# Redis Connection & Caching Layer (Standalone Local Portal Support)
# ---------------------------------------------------------------------------
redis_client = None
try:
    import redis
    redis_host = os.environ.get("REDIS_HOST", "localhost")
    redis_port = int(os.environ.get("REDIS_PORT", 6379))
    redis_client = redis.Redis(host=redis_host, port=redis_port, db=0, decode_responses=True, socket_timeout=2)
    redis_client.ping()
    print(f"✓ Connected to Redis Server at {redis_host}:{redis_port}")
except Exception as re_err:
    print(f"Notice: Redis server connection not active ({re_err}). Operating with memory store.")
    redis_client = None

SEED_CLAIMS = [
    {
        "claim_id": "CLM-2026-00439",
        "policy_number": "POL-2024-88901",
        "claimant_id": "MEM-IN-9081",
        "date_of_loss": "2026-08-26",
        "claimed_amount": 380000,
        "days_since_inception": 1319,
        "claim_velocity": 3,
        "amount_to_premium_ratio": 0.92,
        "status": "PENDING"
    },
    {
        "claim_id": "CLM-41674",
        "policy_number": "POL-2024-44552",
        "claimant_id": "MEM-IN-4410",
        "date_of_loss": "2026-08-26",
        "claimed_amount": 245000,
        "days_since_inception": 909,
        "claim_velocity": 1,
        "amount_to_premium_ratio": 0.86,
        "status": "PENDING"
    },
    {
        "claim_id": "CLM-2026-00437",
        "policy_number": "POL-2024-99331",
        "claimant_id": "MEM-IN-1902",
        "date_of_loss": "2026-08-25",
        "claimed_amount": 195000,
        "days_since_inception": 1539,
        "claim_velocity": 2,
        "amount_to_premium_ratio": 0.68,
        "status": "PENDING"
    },
    {
        "claim_id": "CLM-2026-00441",
        "policy_number": "POL-2024-11223",
        "claimant_id": "MEM-IN-3321",
        "date_of_loss": "2026-08-24",
        "claimed_amount": 98000,
        "days_since_inception": 1838,
        "claim_velocity": 0,
        "amount_to_premium_ratio": 0.15,
        "status": "PROCESSED"
    },
    {
        "claim_id": "CLM-2026-00443",
        "policy_number": "POL-2024-88221",
        "claimant_id": "MEM-IN-7712",
        "date_of_loss": "2026-08-23",
        "claimed_amount": 135000,
        "days_since_inception": 2339,
        "claim_velocity": 4,
        "amount_to_premium_ratio": 0.52,
        "status": "PENDING"
    },
    {
        "claim_id": "CLM-2026-00435",
        "policy_number": "POL-2024-55112",
        "claimant_id": "MEM-IN-6643",
        "date_of_loss": "2026-08-22",
        "claimed_amount": 420000,
        "days_since_inception": 820,
        "claim_velocity": 3,
        "amount_to_premium_ratio": 0.95,
        "status": "PENDING"
    },
    {
        "claim_id": "CLM-2026-00442",
        "policy_number": "POL-2024-33441",
        "claimant_id": "MEM-IN-2291",
        "date_of_loss": "2026-08-21",
        "claimed_amount": 160000,
        "days_since_inception": 1100,
        "claim_velocity": 1,
        "amount_to_premium_ratio": 0.40,
        "status": "PROCESSED"
    },
    {
        "claim_id": "CLM-2026-00440",
        "policy_number": "POL-2024-77665",
        "claimant_id": "MEM-IN-8834",
        "date_of_loss": "2026-08-20",
        "claimed_amount": 290000,
        "days_since_inception": 1450,
        "claim_velocity": 2,
        "amount_to_premium_ratio": 0.72,
        "status": "PENDING"
    },
    {
        "claim_id": "CLM-2026-00434",
        "policy_number": "POL-2024-22998",
        "claimant_id": "MEM-IN-1102",
        "date_of_loss": "2026-08-19",
        "claimed_amount": 115000,
        "days_since_inception": 1900,
        "claim_velocity": 0,
        "amount_to_premium_ratio": 0.25,
        "status": "PROCESSED"
    },
    {
        "claim_id": "CLM-30558",
        "policy_number": "POL-2024-66554",
        "claimant_id": "MEM-IN-5541",
        "date_of_loss": "2026-08-18",
        "claimed_amount": 510000,
        "days_since_inception": 600,
        "claim_velocity": 5,
        "amount_to_premium_ratio": 0.98,
        "status": "PENDING"
    }
]

def seed_redis_if_empty():
    if redis_client:
        try:
            # Re-seed to ensure all 10 claims are available
            redis_client.set("portal:claims", json.dumps(SEED_CLAIMS))
            print("✓ Seeded Redis with 10 active claim records ('portal:claims')")
        except Exception as e:
            print(f"Error seeding Redis: {e}")

seed_redis_if_empty()

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
    """Retrieve claims from Databricks Unity Catalog or Redis fallback."""
    claims = []
    if spark:
        try:
            silver_table = f"{catalog}.{schema}.silver_claims"
            if spark.catalog.tableExists(silver_table):
                from pyspark.sql.window import Window
                from pyspark.sql.functions import row_number, desc, col

                w = Window.partitionBy("claim_id").orderBy(desc("ingested_at"))
                df_silver = (spark.table(silver_table)
                             .withColumn("_rn", row_number().over(w))
                             .filter(col("_rn") == 1)
                             .drop("_rn"))

                gold_table = f"{catalog}.{schema}.gold_claim_decisions"
                processed_ids = set()
                if spark.catalog.tableExists(gold_table):
                    df_gold = spark.table(gold_table).select("claim_id")
                    processed_ids = set(df_gold.toPandas()["claim_id"].tolist())

                df = df_silver.orderBy("claim_id").limit(100).toPandas()
                seen_ids = set()
                for _, row in df.iterrows():
                    cid = str(row["claim_id"])
                    if cid in seen_ids: continue
                    seen_ids.add(cid)
                    claims.append({
                        "claim_id": cid,
                        "policy_number": str(row.get("policy_number") or "POL-2024"),
                        "claimant_id": str(row.get("claimant_id") or "MEM-IN"),
                        "date_of_loss": str(row.get("date_of_loss") or "2026-08-20"),
                        "claimed_amount": int(row.get("claimed_amount") or 0),
                        "days_since_inception": int(row.get("days_since_inception") or 500),
                        "claim_velocity": int(row.get("claim_velocity") or 0),
                        "amount_to_premium_ratio": float(row.get("amount_to_premium_ratio") or 0.0),
                        "status": "PROCESSED" if cid in processed_ids else "PENDING"
                    })
        except Exception as e:
            print(f"Databricks claims fetch error: {e}")

    if claims and len(claims) > 0:
        if redis_client:
            try:
                redis_client.set("portal:claims", json.dumps(claims))
            except Exception:
                pass
        return claims

    # Fallback to Redis / Seed
    if redis_client:
        try:
            cached = redis_client.get("portal:claims")
            if cached:
                res = json.loads(cached)
                if res and len(res) > 0:
                    return res
        except Exception as e:
            print(f"Redis get claims error: {e}")

    return SEED_CLAIMS

@app.post("/api/claims/submit")
def submit_customer_claim(claim_data: dict):
    """Receive new claim submission from Customer Portal and persist into Redis."""
    cid = claim_data.get("claim_id") or f"CLM-{datetime.now().strftime('%M%S')}"
    new_claim = {
        "claim_id": cid,
        "policy_number": claim_data.get("policy_number", "POL-LOCAL"),
        "claimant_id": claim_data.get("claimant_id", "MEM-LOCAL"),
        "date_of_loss": claim_data.get("date_of_loss", datetime.now().strftime("%Y-%m-%d")),
        "claimed_amount": int(claim_data.get("claimed_amount") or 0),
        "days_since_inception": 120,
        "claim_velocity": 1,
        "amount_to_premium_ratio": 0.5,
        "status": "PENDING"
    }

    if redis_client:
        try:
            cached = redis_client.get("portal:claims")
            claims_list = json.loads(cached) if cached else []
            # Check if claim already exists
            existing_idx = next((i for i, c in enumerate(claims_list) if c.get("claim_id") == cid), None)
            if existing_idx is not None:
                claims_list[existing_idx] = new_claim
            else:
                claims_list.insert(0, new_claim)
            redis_client.set("portal:claims", json.dumps(claims_list))
            print(f"✓ Saved customer claim {cid} to Redis")
        except Exception as e:
            print(f"Error saving claim to Redis: {e}")

    return {"status": "SUCCESS", "claim_id": cid, "message": "Claim submitted successfully to Redis"}

@app.post("/api/decide")
def submit_decision(req: DecisionRequest):
    """Record a human adjuster decision in Databricks and Redis."""
    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    recorded_in_db = False
    
    if spark:
        try:
            audit_table = f"{catalog}.{audit_schema}.adjuster_decisions"
            spark.sql(f"""
                INSERT INTO {audit_table} (claim_id, action, reason, user, timestamp)
                VALUES ('{req.claim_id}', '{req.decision}', '{req.reason.replace("'", "''")}', 'Adjuster', current_timestamp())
            """)
            recorded_in_db = True
        except Exception as e:
            print(f"Notice: Could not write decision to Databricks Spark: {e}")

    # Always persist in Redis
    if redis_client:
        try:
            audit_entry = {
                "id": f"AUD-{datetime.now().strftime('%M%S')}",
                "timestamp": timestamp_str,
                "claim_id": req.claim_id,
                "action": req.decision,
                "user": "Claims Officer",
                "reason": req.reason
            }
            redis_client.lpush("portal:audit_trail", json.dumps(audit_entry))

            # Update status in portal:claims
            cached_claims = redis_client.get("portal:claims")
            if cached_claims:
                claims_list = json.loads(cached_claims)
                for c in claims_list:
                    if c.get("claim_id") == req.claim_id:
                        c["status"] = "PROCESSED"
                redis_client.set("portal:claims", json.dumps(claims_list))
        except Exception as re_err:
            print(f"Error persisting decision in Redis: {re_err}")

    return {
        "status": "SUCCESS",
        "message": f"Decision '{req.decision}' recorded for claim {req.claim_id}",
        "db_synced": recorded_in_db
    }

@app.get("/api/review/queue")
def get_review_queue():
    """Retrieve claims assigned to human review based on dashboard view."""
    if spark:
        try:
            dash_view = f"{catalog}.{schema}.vw_claims_dashboard"
            if spark.catalog.tableExists(dash_view):
                df = spark.table(dash_view).toPandas()
                return df.to_dict(orient="records")
        except Exception as e:
            print(f"Error querying dashboard view: {e}")
            
    # Redis Fallback
    if redis_client:
        try:
            cached = redis_client.get("portal:claims")
            if cached:
                all_claims = json.loads(cached)
                return [c for c in all_claims if c.get("status") != "PROCESSED"]
        except Exception:
            pass
            
    return [c for c in SEED_CLAIMS if c.get("status") != "PROCESSED"]

@app.get("/api/review/audit")
def get_audit_trail():
    """Retrieve human decision audits from Databricks or Redis."""
    if spark:
        try:
            audit_table = f"{catalog}.{audit_schema}.adjuster_decisions"
            if spark.catalog.tableExists(audit_table):
                from pyspark.sql.functions import col
                df = spark.table(audit_table).orderBy(col("timestamp").desc()).limit(30).toPandas()
                return df.to_dict(orient="records")
        except Exception as e:
            print(f"Error loading audit trail from Databricks: {e}")

    # Redis Fallback
    if redis_client:
        try:
            raw_entries = redis_client.lrange("portal:audit_trail", 0, 30)
            if raw_entries:
                return [json.loads(e) for e in raw_entries]
        except Exception as re_err:
            print(f"Error loading audit trail from Redis: {re_err}")

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

@app.get("/api/providers")
def get_providers():
    """Retrieve hospital and provider network metrics from Databricks."""
    if not spark:
        return []
    try:
        table_name = f"{catalog}.{schema}.network_hospitals"
        if spark.catalog.tableExists(table_name):
            df = spark.table(table_name).toPandas()
            return df.to_dict(orient="records")
        return []
    except Exception as e:
        print(f"Error loading providers: {e}")
        return []

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
