# Databricks notebook source
# MAGIC %md
# MAGIC # 00 — Setup
# MAGIC **Purpose:** Create Unity Catalog resources (catalog, schemas, volumes) for the Health Claims Accelerator.
# MAGIC **Run this once per environment before any other notebook.**
# MAGIC **Author:** SNS Square | **Version:** 1.0 | **Last Updated:** May 2026
# MAGIC **Prerequisites:** Unity Catalog enabled, CREATE CATALOG privilege on metastore.

# COMMAND ----------

# DBTITLE 1,Parameters — edit via widgets, never hardcode
dbutils.widgets.text("catalog", "health_claims_dev", "Catalog Name")
dbutils.widgets.text("schema", "claims", "Schema Name")
dbutils.widgets.text("env", "dev", "Environment (dev/staging/prod)")

catalog = dbutils.widgets.get("catalog")
schema  = dbutils.widgets.get("schema")
env     = dbutils.widgets.get("env")

print(f"Setting up: {catalog}.{schema} (env={env})")

# COMMAND ----------

# DBTITLE 1,Create catalog
spark.sql(f"CREATE CATALOG IF NOT EXISTS `{catalog}`")
spark.sql(f"USE CATALOG `{catalog}`")
print(f"✓ Catalog '{catalog}' ready")

# COMMAND ----------

# DBTITLE 1,Create schemas
for s in ["claims", "ml_models", "vectors", "audit"]:
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.`{s}`")
    print(f"✓ Schema '{catalog}.{s}' ready")

# COMMAND ----------

# DBTITLE 1,Create Unity Catalog Volumes (for PDFs and unstructured docs)
spark.sql(f"""
    CREATE VOLUME IF NOT EXISTS `{catalog}`.`claims`.`raw_documents`
    COMMENT 'Raw claim documents — discharge summaries, hospital bills, prescriptions'
""")

spark.sql(f"""
    CREATE VOLUME IF NOT EXISTS `{catalog}`.`claims`.`policy_forms`
    COMMENT 'Health insurance policy form documents for Coverage RAG agent'
""")

spark.sql(f"""
    CREATE VOLUME IF NOT EXISTS `{catalog}`.`claims`.`synthetic_data`
    COMMENT 'Generated synthetic claims and policy data for MVP'
""")

print("✓ UC Volumes ready")

# COMMAND ----------

# DBTITLE 1,Tag catalog with environment metadata
spark.sql(f"ALTER CATALOG `{catalog}` SET TAGS ('env' = '{env}', 'project' = 'health-claims-accelerator', 'owner' = 'sns-square')")
print("✓ Catalog tagged")

# COMMAND ----------

# DBTITLE 1,Verify setup — print summary
summary = spark.sql(f"""
    SELECT schema_name 
    FROM `{catalog}`.information_schema.schemata
    ORDER BY schema_name
""").collect()

print(f"\n=== Setup Complete: {catalog} ===")
for row in summary:
    print(f"  Schema: {row.schema_name}")

volumes = spark.sql(f"SHOW VOLUMES IN `{catalog}`.`claims`").collect()
for row in volumes:
    print(f"  Volume: {row.volume_name}")

# COMMAND ----------

# DBTITLE 1,Seed Gold Reference Tables from Synthetic CSVs
import os

repo_root = "."
if os.path.exists("../data/raw/structured/policy_master.csv"):
    repo_root = ".."

def seed_gold_table(csv_name, table_name):
    csv_path = f"file:" + os.path.abspath(f"{repo_root}/data/raw/structured/{csv_name}")
    try:
        df = spark.read.csv(csv_path, header=True, inferSchema=True)
        df.write.format("delta").mode("overwrite").saveAsTable(f"`{catalog}`.`claims`.`{table_name}`")
        print(f"✓ Seeded {table_name} ({df.count()} rows)")
    except Exception as e:
        print(f"Failed to seed {table_name}. Did you run generate_synthetic_data.py? Error: {e}")

seed_gold_table("policy_master.csv", "policy_master")
seed_gold_table("claims_history.csv", "claims_history")
seed_gold_table("network_hospitals.csv", "network_hospitals")


# COMMAND ----------

# DBTITLE 1,Create adjuster decisions audit table
spark.sql(f"""
    CREATE TABLE IF NOT EXISTS `{catalog}`.`audit`.`adjuster_decisions` (
        claim_id STRING,
        user STRING,
        action STRING,
        reason STRING,
        timestamp STRING
    ) USING delta
""")
print("✓ Table audit.adjuster_decisions ready")

# COMMAND ----------

# DBTITLE 1,Write setup completion record to audit log
from datetime import datetime
import json

audit_data = [{
    "event": "SETUP_COMPLETE",
    "catalog": catalog,
    "schema": schema,
    "env": env,
    "timestamp": datetime.utcnow().isoformat(),
    "run_by": spark.sql("SELECT current_user()").collect()[0][0]
}]

(spark.createDataFrame(audit_data)
     .write
     .format("delta")
     .mode("append")
     .saveAsTable(f"`{catalog}`.`audit`.`setup_log`"))

print("✓ Audit log entry written")
print("\nRun notebooks in this order next: 01 → 02 → 03 → 04 → 05 → 06 → 07")