# Databricks notebook source
# MAGIC %md
# MAGIC # 01 Bronze Ingestion
# MAGIC Ingests structured claims from raw CSV to a Bronze Delta Table and copies unstructured text to UC Volumes.

# COMMAND ----------

import os
from pyspark.sql.functions import current_timestamp, lit

# Read from widgets
dbutils.widgets.text("catalog", "health_claims_dev")
dbutils.widgets.text("schema", "claims")

CATALOG_NAME = dbutils.widgets.get("catalog")
SCHEMA_NAME = dbutils.widgets.get("schema")
VOLUME_NAME = "raw_documents"

spark.sql(f"USE {CATALOG_NAME}.{SCHEMA_NAME}")

# COMMAND ----------

# Define Explicit DDL Schema and apply PHI masking
schema_ddl = f"""
CREATE TABLE IF NOT EXISTS {CATALOG_NAME}.{SCHEMA_NAME}.bronze_claims (
    claim_id STRING,
    policy_number STRING,
    claimant_name STRING,
    date_of_loss STRING,
    hospital_name STRING,
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
"""
spark.sql(schema_ddl)

masking_func_ddl = f"""
CREATE OR REPLACE FUNCTION {CATALOG_NAME}.{SCHEMA_NAME}.phi_masking(claimant_name STRING)
RETURN CASE WHEN is_account_group_member('health_claims_auditors') THEN claimant_name ELSE '***MASKED***' END;
"""
spark.sql(masking_func_ddl)

masking_apply_ddl = f"""
ALTER TABLE {CATALOG_NAME}.{SCHEMA_NAME}.bronze_claims ALTER COLUMN claimant_name SET MASK {CATALOG_NAME}.{SCHEMA_NAME}.phi_masking;
"""
spark.sql(masking_apply_ddl)

# COMMAND ----------

# 1. Ingest Structured CSV to Bronze Table
# Dynamically find repo root
if os.path.exists("./data/raw/structured/claims.csv"):
    repo_root = "."
elif os.path.exists("../data/raw/structured/claims.csv"):
    repo_root = ".."
else:
    raise FileNotFoundError("Could not find the data directory. Did you run generate_synthetic_data.py?")

raw_csv_path = "file:" + os.path.abspath(f"{repo_root}/data/raw/structured/claims.csv")
print(f"Reading from {raw_csv_path}")

df_raw = spark.read.csv(raw_csv_path, header=True, inferSchema=True)
df_bronze = df_raw.withColumn("ingested_at", current_timestamp()) \
                  .withColumn("source", lit(raw_csv_path))

# Write to Bronze Delta Table (Append-only) WITHOUT mergeSchema to enforce schema
bronze_table = f"{CATALOG_NAME}.{SCHEMA_NAME}.bronze_claims"
print(f"Writing to {bronze_table}")
df_bronze.write.format("delta").mode("append").saveAsTable(bronze_table)

# COMMAND ----------

# 2. Copy data to UC Volumes
# In a real scenario, Auto Loader / external system would land files directly in the Volume.
# Here, we copy our synthetic text files to the volume paths.
# Databricks volume paths look like /Volumes/catalog/schema/volume/

volumes_to_copy = {
    "raw_documents": f"file:{os.path.abspath(f'{repo_root}/data/raw/unstructured')}",
    "policy_forms": f"file:{os.path.abspath(f'{repo_root}/data/policy_forms')}",
    "synthetic_data": f"file:{os.path.abspath(f'{repo_root}/data/raw/structured')}"
}

for vol_name, local_dir in volumes_to_copy.items():
    volume_path = f"/Volumes/{CATALOG_NAME}/{SCHEMA_NAME}/{vol_name}/"
    print(f"Simulating copy of data to {volume_path}")
    try:
        # If dbutils.fs is available, we copy to the volume
        dbutils.fs.mkdirs(volume_path)
        dbutils.fs.cp(local_dir, volume_path, recurse=True)
        print(f"Files copied to {vol_name} successfully.")
    except Exception as e:
        print(f"Could not copy files to {vol_name} (expected if running outside Databricks). {e}")

print("Bronze ingestion complete.")