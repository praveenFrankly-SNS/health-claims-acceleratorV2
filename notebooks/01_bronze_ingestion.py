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
dbutils.widgets.text("use_supabase", "false")
dbutils.widgets.text("supabase_host", "")
dbutils.widgets.text("supabase_port", "5432")
dbutils.widgets.text("supabase_db", "postgres")

CATALOG_NAME = dbutils.widgets.get("catalog")
SCHEMA_NAME = dbutils.widgets.get("schema")
USE_SUPABASE = dbutils.widgets.get("use_supabase").lower() == "true"
DB_HOST = dbutils.widgets.get("supabase_host")
DB_PORT = dbutils.widgets.get("supabase_port")
DB_NAME = dbutils.widgets.get("supabase_db")
VOLUME_NAME = "raw_documents"

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
        print("✓ Successfully loaded credentials from Databricks Secrets scope 'supabase'")
    except Exception as e:
        print(f"Notice: Databricks Secrets scope 'supabase' not found or inaccessible: {e}")
        
        # 2. Fallback to environment variables
        DB_USER = os.environ.get("SUPABASE_USER", "")
        DB_PASSWORD = os.environ.get("SUPABASE_PASSWORD", "")
        if DB_USER and DB_PASSWORD:
            print("✓ Successfully loaded credentials from environment variables")
        else:
            print("Warning: Database credentials not found in secrets or environment variables. JDBC loading may fail.")

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

# DBTITLE 1,Helper Function for Ingestion
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

# DBTITLE 1,Bronze Ingestion — Claim Submissions (append-only)
df_raw_submissions = load_source_table("claim_submissions", "claim_submissions.csv")
df_submissions_bronze = df_raw_submissions.withColumn("ingested_at", current_timestamp())

bronze_submissions_table = f"{CATALOG_NAME}.{SCHEMA_NAME}.bronze_claim_submissions"

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {bronze_submissions_table} (
    claim_id STRING,
    policy_number STRING,
    claimant_id STRING,
    date_of_loss STRING,
    claimed_amount INT,
    submission_date STRING,
    status STRING,
    is_fraud INT,
    ingested_at TIMESTAMP,
    source STRING
)
TBLPROPERTIES (
    'sensitivity'='PHI',
    'classification'='restricted'
)
""")

df_submissions_bronze.write.format("delta").mode("append").saveAsTable(bronze_submissions_table)
print(f"✓ Ingested {df_submissions_bronze.count()} rows to {bronze_submissions_table}")

# COMMAND ----------

# DBTITLE 1,Bronze Ingestion — Pre-Auth Requests
df_raw_pa = load_source_table("pre_auth_requests", "pre_auth_requests.csv")
df_pa_bronze = df_raw_pa.withColumn("ingested_at", current_timestamp())

bronze_pa_table = f"{CATALOG_NAME}.{SCHEMA_NAME}.bronze_pre_auth_requests"
df_pa_bronze.write.format("delta").mode("overwrite").saveAsTable(bronze_pa_table)
print(f"✓ Ingested {df_pa_bronze.count()} rows to {bronze_pa_table}")

# COMMAND ----------

# DBTITLE 1,Bronze Ingestion — Clinical Records
df_raw_cr = load_source_table("clinical_records", "clinical_records.csv")
df_cr_bronze = df_raw_cr.withColumn("ingested_at", current_timestamp())

bronze_cr_table = f"{CATALOG_NAME}.{SCHEMA_NAME}.bronze_clinical_records"
df_cr_bronze.write.format("delta").mode("overwrite").saveAsTable(bronze_cr_table)
print(f"✓ Ingested {df_cr_bronze.count()} rows to {bronze_cr_table}")

# COMMAND ----------

# DBTITLE 1,Bronze Ingestion — Claim Bills
df_raw_bills = load_source_table("claim_bills", "claim_bills.csv")
df_bills_bronze = df_raw_bills.withColumn("ingested_at", current_timestamp())

bronze_bills_table = f"{CATALOG_NAME}.{SCHEMA_NAME}.bronze_claim_bills"
df_bills_bronze.write.format("delta").mode("overwrite").saveAsTable(bronze_bills_table)
print(f"✓ Ingested {df_bills_bronze.count()} rows to {bronze_bills_table}")

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
            df_ref.write.format("delta").mode("overwrite").saveAsTable(target_ref_table)
            print(f"✓ Synced reference table {target_ref_table} ({df_ref.count()} rows)")
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
    
    # Download from Supabase Storage using the Supabase Python client (if available)
    # Fallback: use HTTP requests to download from Supabase Storage REST API
    supabase_url = DB_HOST.replace("db.", "") if DB_HOST else ""
    if not supabase_url:
        supabase_url = os.environ.get("SUPABASE_URL", "")
    
    supabase_key = DB_PASSWORD or os.environ.get("SUPABASE_SERVICE_KEY", "")
    
    for bucket_name, config in supabase_buckets.items():
        volume_path = config["volume"]
        print(f"  Downloading from Supabase Storage bucket '{bucket_name}' to {volume_path}")
        try:
            dbutils.fs.mkdirs(volume_path)
            
            # Use the Supabase Storage REST API to list and download files
            list_url = f"{supabase_url}/storage/v1/object/list/{bucket_name}"
            headers = {
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}"
            }
            
            import requests as req
            response = req.post(list_url, json={"prefix": config["prefix"], "limit": 200}, headers=headers)
            
            if response.status_code == 200:
                files = response.json()
                for file_info in files:
                    file_name = file_info.get("name", "")
                    if not file_name or file_name.endswith("/"):
                        continue
                        
                    download_url = f"{supabase_url}/storage/v1/object/public/{bucket_name}/{file_name}"
                    print(f"    Downloading: {file_name}")
                    
                    # Use dbutils.fs.cp with HTTP URL (works in Databricks Runtime 10+)
                    dest_path = os.path.join(volume_path, os.path.basename(file_name))
                    dbutils.fs.cp(download_url, dest_path)
                    
                print(f"  ✓ Downloaded files from bucket '{bucket_name}'")
            else:
                print(f"  ⚠ Failed to list files in bucket '{bucket_name}': {response.status_code} {response.text}")
                
        except Exception as e:
            print(f"  ⚠ Could not download from bucket '{bucket_name}': {e}")
    
    print("✓ Supabase Storage download complete.")
