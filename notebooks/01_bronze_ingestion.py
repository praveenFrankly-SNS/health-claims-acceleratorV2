# Databricks notebook source
# MAGIC %md
# MAGIC # 01 Bronze Ingestion
# MAGIC Ingests structured claims data from Supabase PostgreSQL (via JDBC) or raw CSVs
# MAGIC to Bronze Delta Tables and copies unstructured text to UC Volumes.
# MAGIC
# MAGIC **Author:** SNS Square | **Version:** 2.1 | **Last Updated:** June 2026

# COMMAND ----------

import os
from pyspark.sql.functions import current_timestamp, lit

# Read from widgets
dbutils.widgets.text("catalog", "health_claims_dev")
dbutils.widgets.text("schema", "claims")
dbutils.widgets.text("use_supabase", "true")
dbutils.widgets.text("supabase_host", "aws-1-ap-northeast-1.pooler.supabase.com")
dbutils.widgets.text("supabase_port", "5432")
dbutils.widgets.text("supabase_db", "postgres")
dbutils.widgets.text("supabase_user", "postgres.nerwqbauracfinfvunul")
dbutils.widgets.text("supabase_password", "")
dbutils.widgets.text("supabase_service_key", "")   # Supabase service role JWT — for Storage API auth

CATALOG_NAME = dbutils.widgets.get("catalog")
SCHEMA_NAME = dbutils.widgets.get("schema")
USE_SUPABASE = dbutils.widgets.get("use_supabase").lower() == "true"
DB_HOST = dbutils.widgets.get("supabase_host")
DB_PORT = dbutils.widgets.get("supabase_port")
DB_NAME = dbutils.widgets.get("supabase_db")
VOLUME_NAME = "raw_documents"

print(f"Config: catalog={CATALOG_NAME}, schema={SCHEMA_NAME}, use_supabase={USE_SUPABASE}")
spark.sql(f"USE {CATALOG_NAME}.{SCHEMA_NAME}")

# COMMAND ----------

# DBTITLE 1,Resolve Database Credentials Securely
DB_USER = ""
DB_PASSWORD = ""

if USE_SUPABASE:
    # 1. Attempt loading from Databricks Secrets
    try:
        DB_USER = dbutils.secrets.get(scope="supabase", key="user")
        DB_PASSWORD = dbutils.secrets.get(scope="supabase", key="password")
        print("✓ Credentials loaded from Databricks Secrets scope 'supabase'")
    except Exception as e:
        print(f"Notice: Databricks Secrets not available: {e}")

        # 2. Fallback to environment variables
        DB_USER = os.environ.get("SUPABASE_USER", "")
        DB_PASSWORD = os.environ.get("SUPABASE_PASSWORD", "")

        # 3. Fallback to job widgets (most common for first-time runs)
        if not DB_USER:
            DB_USER = dbutils.widgets.get("supabase_user")
        if not DB_PASSWORD:
            DB_PASSWORD = dbutils.widgets.get("supabase_password")

        if DB_USER and DB_PASSWORD:
            print("✓ Credentials loaded from widgets / environment variables")
        elif DB_USER and not DB_PASSWORD:
            print("⚠ DB_USER resolved but DB_PASSWORD is empty — JDBC will fail. Set supabase_password in job parameters.")
        else:
            print("⚠ No credentials found. Set supabase_user/supabase_password in job parameters.")

# -----------------------------------------------------------------------
# Resolve Supabase Storage credentials — SEPARATE from JDBC DB password.
# Priority: widget supabase_service_key → env var SUPABASE_SERVICE_KEY
#
# supabase_service_key = the service role JWT from Supabase Dashboard
#   → Project Settings → API → service_role key
#   (starts with "sb_secret_..." or "eyJ...")
# DB_PASSWORD = the PostgreSQL password — NOT the same thing.
# -----------------------------------------------------------------------
_widget_service_key = dbutils.widgets.get("supabase_service_key")
SUPABASE_SERVICE_KEY = (
    _widget_service_key.strip()
    or os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
)

# Derive Supabase project REST URL from user (format: postgres.<project_ref>)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
if not SUPABASE_URL and DB_USER and "." in DB_USER:
    _ref = DB_USER.split(".")[-1]
    SUPABASE_URL = f"https://{_ref}.supabase.co"

print(f"  Supabase URL:         {SUPABASE_URL or 'NOT SET'}")
print(f"  DB password present:  {bool(DB_PASSWORD)}")
print(f"  Service key present:  {bool(SUPABASE_SERVICE_KEY)}")
if not SUPABASE_SERVICE_KEY:
    print("  ⚠ supabase_service_key is empty — Storage download will be skipped.")
    print("    Set it in job parameters: supabase_service_key = sb_secret_rT_ljNuqMXqkSW_zi_9UeA_HXbMKZi6")

# COMMAND ----------

# DBTITLE 1,Find Repo Root
if os.path.exists("./data/raw/structured/claim_submissions.csv"):
    repo_root = "."
elif os.path.exists("../data/raw/structured/claim_submissions.csv"):
    repo_root = ".."
else:
    repo_root = "."
    print("Notice: Local raw CSV files not found. Ingestion will fail if fallback is triggered.")

print(f"Repo root path: {os.path.abspath(repo_root)}")

# COMMAND ----------

def write_bronze_table(df, table_name: str):
    """
    Write a DataFrame to a Delta bronze table.
    Uses overwrite + overwriteSchema=true so re-runs never fail with
    DELTA_METADATA_MISMATCH even if the table schema changed between runs.
    """
    df.write \
      .format("delta") \
      .mode("overwrite") \
      .option("overwriteSchema", "true") \
      .saveAsTable(table_name)
    print(f"✓ Written {df.count()} rows to {table_name}")


def load_source_table(table_name: str, csv_filename: str):
    """Loads a table from Supabase Postgres JDBC if enabled, otherwise falls back to local CSV."""
    if USE_SUPABASE:
        if not DB_HOST:
            raise ValueError("supabase_host parameter is required when use_supabase is enabled")
        
        jdbc_url = f"jdbc:postgresql://{DB_HOST}:{DB_PORT}/{DB_NAME}?ssl=true&sslmode=require"
        print(f"Ingesting table '{table_name}' from Supabase PostgreSQL: {DB_HOST}")
        
        return spark.read \
            .format("jdbc") \
            .option("url", jdbc_url) \
            .option("dbtable", f"public.{table_name}") \
            .option("user", DB_USER) \
            .option("password", DB_PASSWORD) \
            .option("driver", "org.postgresql.Driver") \
            .load() \
            .withColumn("source", lit(f"jdbc:postgresql://{DB_HOST}/{DB_NAME}/{table_name}"))
    else:
        csv_path = f"file:{os.path.abspath(f'{repo_root}/data/raw/structured/{csv_filename}')}"
        print(f"Reading '{table_name}' from local CSV: {csv_path}")
        
        return spark.read.csv(csv_path, header=True, inferSchema=True) \
            .withColumn("source", lit(csv_path))

# COMMAND ----------

# DBTITLE 1,Bronze Ingestion — Claim Submissions (overwrite — safe to re-run)
df_raw_submissions = load_source_table("claim_submissions", "claim_submissions.csv")
df_submissions_bronze = df_raw_submissions.withColumn("ingested_at", current_timestamp())

bronze_submissions_table = f"{CATALOG_NAME}.{SCHEMA_NAME}.bronze_claim_submissions"

# overwriteSchema=true handles DELTA_METADATA_MISMATCH from any prior run
write_bronze_table(df_submissions_bronze, bronze_submissions_table)

# COMMAND ----------

# DBTITLE 1,Bronze Ingestion — Claim Submissions Training (full historical set, overwrite)
bronze_training_table = f"{CATALOG_NAME}.{SCHEMA_NAME}.bronze_claim_submissions_training"

try:
    df_raw_training = load_source_table("claim_submissions_training", "claim_submissions.csv")
    df_training_bronze = df_raw_training.withColumn("ingested_at", current_timestamp())
    write_bronze_table(df_training_bronze, bronze_training_table)
    print(f"  → {bronze_training_table} holds the full 450-row training set for fraud model")
except Exception as e:
    print(f"⚠ Could not load claim_submissions_training: {e}")
    print("  Falling back: using bronze_claim_submissions as training table")
    write_bronze_table(df_submissions_bronze, bronze_training_table)

# COMMAND ----------

# DBTITLE 1,Bronze Ingestion — Pre-Auth Requests
df_raw_pa = load_source_table("pre_auth_requests", "pre_auth_requests.csv")
df_pa_bronze = df_raw_pa.withColumn("ingested_at", current_timestamp())
write_bronze_table(df_pa_bronze, f"{CATALOG_NAME}.{SCHEMA_NAME}.bronze_pre_auth_requests")

# COMMAND ----------

# DBTITLE 1,Bronze Ingestion — Clinical Records
df_raw_cr = load_source_table("clinical_records", "clinical_records.csv")
df_cr_bronze = df_raw_cr.withColumn("ingested_at", current_timestamp())
write_bronze_table(df_cr_bronze, f"{CATALOG_NAME}.{SCHEMA_NAME}.bronze_clinical_records")

# COMMAND ----------

# DBTITLE 1,Bronze Ingestion — Claim Bills
df_raw_bills = load_source_table("claim_bills", "claim_bills.csv")
df_bills_bronze = df_raw_bills.withColumn("ingested_at", current_timestamp())
write_bronze_table(df_bills_bronze, f"{CATALOG_NAME}.{SCHEMA_NAME}.bronze_claim_bills")

# COMMAND ----------

# DBTITLE 1,Reference Data Sync (Only if using Supabase as source of truth)
if USE_SUPABASE:
    print("\nSyncing reference tables from Supabase...")
    
    reference_tables = [
        ("network_hospitals", "network_hospitals.csv"),
        ("provider_registry", "provider_registry.csv"),
        ("policy_master", "policy_master.csv"),
        ("policy_members", "policy_members.csv")
    ]
    
    for table_name, csv_file in reference_tables:
        try:
            df_ref = load_source_table(table_name, csv_file)
            target_ref_table = f"{CATALOG_NAME}.{SCHEMA_NAME}.{table_name}"
            write_bronze_table(df_ref, target_ref_table)
        except Exception as e:
            print(f"⚠ Failed to sync reference table {table_name}: {e}")

# COMMAND ----------

# DBTITLE 1,Copy Unstructured Docs to UC Volumes (Local CSV mode)
if not USE_SUPABASE:
    volumes_to_copy = {
        "raw_documents": f"file:{os.path.abspath(f'{repo_root}/data/raw/unstructured')}",
        "policy_forms": f"file:{os.path.abspath(f'{repo_root}/data/policy_forms')}",
        "synthetic_data": f"file:{os.path.abspath(f'{repo_root}/data/raw/structured')}"
    }

    for vol_name, local_dir in volumes_to_copy.items():
        volume_path = f"/Volumes/{CATALOG_NAME}/{SCHEMA_NAME}/{vol_name}/"
        print(f"Copying data to {volume_path}")
        try:
            if os.path.exists(local_dir.replace("file:", "")):
                dbutils.fs.mkdirs(volume_path)
                dbutils.fs.cp(local_dir, volume_path, recurse=True)
                print(f"✓ Files copied to volume {vol_name} successfully.")
            else:
                print(f"Skipping {vol_name}: Source path {local_dir} does not exist.")
        except Exception as e:
            print(f"Could not copy files to volume {vol_name} (expected if running outside Databricks). {e}")
else:
    print("Local CSV mode disabled: 'use_supabase' is enabled. Files must be uploaded to Supabase Storage.")

# DBTITLE 1,Download Unstructured Docs from Supabase Storage to UC Volumes (Supabase mode)
if USE_SUPABASE:
    print("\nDownloading unstructured documents from Supabase Storage to UC Volumes...")

    if SUPABASE_URL and SUPABASE_SERVICE_KEY:
        import requests as req

        # bucket_name -> (volume destination path, folder prefix inside bucket)
        supabase_buckets = {
            "claim-discharges": {
                "volume": f"/Volumes/{CATALOG_NAME}/{SCHEMA_NAME}/raw_documents/discharge-summaries/",
                "prefix": "discharge-summaries/"
            },
            "claim-bills": {
                "volume": f"/Volumes/{CATALOG_NAME}/{SCHEMA_NAME}/raw_documents/hospital-bills/",
                "prefix": "hospital-bills/"
            },
            "policy-forms": {
                "volume": f"/Volumes/{CATALOG_NAME}/{SCHEMA_NAME}/policy_forms/",
                "prefix": "policy-forms/"
            }
        }

        auth_headers = {
            "apikey": SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}"
        }

        for bucket_name, config in supabase_buckets.items():
            volume_path = config["volume"]
            prefix = config["prefix"]
            print(f"\n  Bucket '{bucket_name}' → {volume_path}")

            try:
                dbutils.fs.mkdirs(volume_path)
                # Also ensure directory exists for Python's open() on Serverless
                os.makedirs(volume_path, exist_ok=True)

                # List all files in the bucket folder via REST API
                list_url = f"{SUPABASE_URL}/storage/v1/object/list/{bucket_name}"
                list_resp = req.post(
                    list_url,
                    json={"prefix": prefix, "limit": 500, "offset": 0,
                          "sortBy": {"column": "name", "order": "asc"}},
                    headers=auth_headers,
                    timeout=30
                )

                if list_resp.status_code != 200:
                    print(f"  ⚠ List failed ({list_resp.status_code}): {list_resp.text[:200]}")
                    continue

                file_list = list_resp.json()
                if not isinstance(file_list, list):
                    print(f"  ⚠ Unexpected list response: {file_list}")
                    continue

                # Filter out folder entries (id is None for virtual folders)
                file_entries = [f for f in file_list if f.get("id") is not None]
                print(f"    Found {len(file_entries)} file(s) in bucket")

                downloaded = 0
                skipped = 0
                for file_info in file_entries:
                    # Supabase list API returns 'name' RELATIVE to the prefix we searched with.
                    file_name = file_info.get("name", "")
                    if not file_name:
                        continue

                    # Build the full object path used in the download URL
                    if file_name.startswith(prefix):
                        object_path = file_name
                    else:
                        object_path = f"{prefix}{file_name}"

                    base_name = os.path.basename(object_path)
                    # Write directly to UC Volume using Python open() — no temp file needed.
                    # dbutils.fs.cp("file:/tmp/...") is blocked on Serverless compute.
                    local_vol_path = f"{volume_path}{base_name}"

                    # Download via authenticated GET — works for private buckets with service key
                    download_url = f"{SUPABASE_URL}/storage/v1/object/{bucket_name}/{object_path}"
                    try:
                        dl_resp = req.get(download_url, headers=auth_headers, timeout=60, stream=True)
                        if dl_resp.status_code == 200:
                            # Write binary content directly to UC Volume path
                            # UC Volumes support standard Python open() on Serverless
                            with open(local_vol_path, "wb") as out_f:
                                for chunk in dl_resp.iter_content(chunk_size=65536):
                                    out_f.write(chunk)
                            downloaded += 1
                        else:
                            print(f"    ⚠ Download failed for '{object_path}': HTTP {dl_resp.status_code} — {dl_resp.text[:100]}")
                            skipped += 1
                    except Exception as dl_err:
                        print(f"    ⚠ Error downloading '{object_path}': {dl_err}")
                        skipped += 1

                print(f"  ✓ Bucket '{bucket_name}': {downloaded} downloaded, {skipped} skipped")

            except Exception as bucket_err:
                print(f"  ⚠ Could not process bucket '{bucket_name}': {bucket_err}")

        print("\n✓ Supabase Storage download complete.")
    else:
        print("  ⚠ Skipping Storage download: SUPABASE_URL or SUPABASE_SERVICE_KEY not available.")
        print("  Set SUPABASE_URL and SUPABASE_SERVICE_KEY as Databricks environment variables,")
        print("  or ensure supabase_user is in 'postgres.<project_ref>' format.")
