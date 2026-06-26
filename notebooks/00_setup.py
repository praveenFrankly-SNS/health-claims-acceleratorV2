# Databricks notebook source
# MAGIC %md
# MAGIC # 00 — Setup
# MAGIC **Purpose:** Create Unity Catalog resources (catalog, schemas, volumes) and Delta table DDLs
# MAGIC for the Health Claims Accelerator v2 relational schema.
# MAGIC **Run this once per environment before any other notebook.**
# MAGIC **Version:** 2.0 | **Last Updated:** June 2026
# MAGIC **Prerequisites:** Unity Catalog enabled, CREATE CATALOG privilege on metastore.

# COMMAND ----------

# DBTITLE 1,Parameters — edit via widgets, never hardcode
dbutils.widgets.text("catalog", "health_claims_dev", "Catalog Name")
dbutils.widgets.text("schema", "claims", "Schema Name")
dbutils.widgets.text("env", "dev", "Environment (dev/staging/prod)")
dbutils.widgets.text("use_supabase", "false", "Use Supabase")

catalog = dbutils.widgets.get("catalog")
schema  = dbutils.widgets.get("schema")
env     = dbutils.widgets.get("env")
use_supabase = dbutils.widgets.get("use_supabase").lower() == "true"

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

# DBTITLE 1,Table DDLs — v2 Relational Schema

# ---- network_hospitals ----
spark.sql(f"""
    CREATE TABLE IF NOT EXISTS `{catalog}`.`{schema}`.`network_hospitals` (
        hospital_id STRING NOT NULL,
        hospital_name STRING,
        tier STRING,
        network_status STRING,
        CONSTRAINT pk_network_hospitals PRIMARY KEY (hospital_id)
    ) USING delta
    TBLPROPERTIES ('sensitivity'='INTERNAL')
""")
print("✓ Table network_hospitals ready")

# ---- provider_registry ----
spark.sql(f"""
    CREATE TABLE IF NOT EXISTS `{catalog}`.`{schema}`.`provider_registry` (
        physician_registration_number STRING NOT NULL,
        physician_name STRING,
        hospital_id STRING,
        blacklist_status BOOLEAN,
        historical_claim_count INT,
        historical_fraud_flag_ratio DOUBLE,
        CONSTRAINT pk_provider_registry PRIMARY KEY (physician_registration_number)
    ) USING delta
    TBLPROPERTIES ('sensitivity'='INTERNAL')
""")
print("✓ Table provider_registry ready")

# ---- policy_master ----
spark.sql(f"""
    CREATE TABLE IF NOT EXISTS `{catalog}`.`{schema}`.`policy_master` (
        policy_number STRING NOT NULL,
        policy_type STRING COMMENT 'FLOATER or INDIVIDUAL',
        total_sum_insured INT,
        inception_date STRING,
        premium_paid INT,
        status STRING COMMENT 'ACTIVE, RENEWED, LAPSED',
        policy_form_version STRING,
        plan_tier STRING,
        CONSTRAINT pk_policy_master PRIMARY KEY (policy_number)
    ) USING delta
    TBLPROPERTIES ('sensitivity'='INTERNAL')
""")
print("✓ Table policy_master ready")

# ---- policy_members (composite PK: policy_number + member_id) ----
spark.sql(f"""
    CREATE TABLE IF NOT EXISTS `{catalog}`.`{schema}`.`policy_members` (
        policy_number STRING NOT NULL,
        member_id STRING NOT NULL COMMENT 'Durable ID — persists across renewal terms',
        member_name STRING,
        relationship_to_primary STRING,
        date_of_birth STRING,
        coverage_start_date STRING,
        coverage_end_date STRING,
        CONSTRAINT pk_policy_members PRIMARY KEY (policy_number, member_id)
    ) USING delta
    TBLPROPERTIES ('sensitivity'='PHI', 'classification'='restricted')
""")
print("✓ Table policy_members ready")

# ---- claim_submissions (includes status for investigation tracking) ----
spark.sql(f"""
    CREATE TABLE IF NOT EXISTS `{catalog}`.`{schema}`.`claim_submissions` (
        claim_id STRING NOT NULL,
        policy_number STRING,
        claimant_id STRING COMMENT 'FK to policy_members.member_id',
        date_of_loss STRING,
        claimed_amount INT,
        submission_date STRING,
        status STRING COMMENT 'NEW, INVESTIGATION_PENDING, RESOLVED_FRAUD, RESOLVED_CLEAN',
        is_fraud INT COMMENT 'Ground truth label for training — NOT used in inference',
        CONSTRAINT pk_claim_submissions PRIMARY KEY (claim_id)
    ) USING delta
    TBLPROPERTIES ('sensitivity'='PHI', 'classification'='restricted')
""")
print("✓ Table claim_submissions ready")

# ---- pre_auth_requests ----
spark.sql(f"""
    CREATE TABLE IF NOT EXISTS `{catalog}`.`{schema}`.`pre_auth_requests` (
        pre_auth_id STRING NOT NULL,
        claim_id STRING,
        requested_amount INT,
        approved_amount INT,
        status STRING COMMENT 'APPROVED or DENIED',
        request_date STRING,
        CONSTRAINT pk_pre_auth_requests PRIMARY KEY (pre_auth_id)
    ) USING delta
    TBLPROPERTIES ('sensitivity'='INTERNAL')
""")
print("✓ Table pre_auth_requests ready")

# ---- clinical_records (composite PK: claim_id + record_seq) ----
spark.sql(f"""
    CREATE TABLE IF NOT EXISTS `{catalog}`.`{schema}`.`clinical_records` (
        claim_id STRING NOT NULL,
        record_seq INT NOT NULL,
        admission_date STRING,
        discharge_date STRING,
        hospital_id STRING COMMENT 'FK to network_hospitals.hospital_id',
        diagnosis_icd STRING,
        attending_physician_registration_number STRING COMMENT 'FK to provider_registry',
        CONSTRAINT pk_clinical_records PRIMARY KEY (claim_id, record_seq)
    ) USING delta
    TBLPROPERTIES ('sensitivity'='PHI', 'classification'='restricted')
""")
print("✓ Table clinical_records ready")

# ---- claim_bills (composite PK: claim_id + bill_no) ----
spark.sql(f"""
    CREATE TABLE IF NOT EXISTS `{catalog}`.`{schema}`.`claim_bills` (
        claim_id STRING NOT NULL,
        bill_no STRING NOT NULL,
        bill_date STRING,
        raw_expense_label STRING COMMENT 'Original text from hospital bill',
        normalized_expense_type STRING COMMENT 'ROOM_RENT, PHARMACY, DIAGNOSTICS, CONSULTANT_FEES, AMBULANCE, OTHER',
        amount INT,
        CONSTRAINT pk_claim_bills PRIMARY KEY (claim_id, bill_no)
    ) USING delta
    TBLPROPERTIES ('sensitivity'='PHI', 'classification'='restricted')
""")
print("✓ Table claim_bills ready")

# ---- silver_claim_features (materialized feature table) ----
spark.sql(f"""
    CREATE TABLE IF NOT EXISTS `{catalog}`.`{schema}`.`silver_claim_features` (
        claim_id STRING NOT NULL,
        policy_number STRING,
        claimant_id STRING,
        date_of_loss STRING,
        claimed_amount INT,
        days_since_inception INT,
        amount_to_premium_ratio DOUBLE,
        member_claim_velocity_90d INT,
        policy_claim_velocity_90d INT,
        remaining_sum_insured_balance INT,
        physician_fraud_ratio DOUBLE,
        hospital_billing_velocity_30d INT,
        pre_auth_category STRING COMMENT 'PRE_AUTH_NOT_SOUGHT, PRE_AUTH_DENIED, PRE_AUTH_APPROVED',
        pre_auth_approval_ratio DOUBLE,
        pct_bills_exceeding_structured_limits DOUBLE,
        feature_pipeline_version STRING,
        claimant_name_hash STRING,
        ingested_at TIMESTAMP,
        CONSTRAINT pk_silver_features PRIMARY KEY (claim_id)
    ) USING delta
    TBLPROPERTIES ('sensitivity'='PHI', 'classification'='restricted')
""")
print("✓ Table silver_claim_features ready")

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

# DBTITLE 1,Seed Reference Tables from Synthetic CSVs (Bypassed if using Supabase)
if use_supabase:
    print("Bypassing CSV seeding: Supabase PostgreSQL is enabled as the database source of truth.")
else:
    import os
    repo_root = "."
    if os.path.exists("../data/raw/structured/policy_master.csv"):
        repo_root = ".."

    def seed_table(csv_name, table_name):
        csv_path = f"file:" + os.path.abspath(f"{repo_root}/data/raw/structured/{csv_name}")
        try:
            df = spark.read.csv(csv_path, header=True, inferSchema=True)
            df.write.format("delta").mode("overwrite").saveAsTable(f"`{catalog}`.`{schema}`.`{table_name}`")
            print(f"✓ Seeded {table_name} ({df.count()} rows)")
        except Exception as e:
            print(f"Failed to seed {table_name}. Did you run generate_synthetic_data.py? Error: {e}")

    seed_table("network_hospitals.csv", "network_hospitals")
    seed_table("provider_registry.csv", "provider_registry")
    seed_table("policy_master.csv", "policy_master")
    seed_table("policy_members.csv", "policy_members")
    seed_table("claim_submissions.csv", "claim_submissions")
    seed_table("pre_auth_requests.csv", "pre_auth_requests")
    seed_table("clinical_records.csv", "clinical_records")
    seed_table("claim_bills.csv", "claim_bills")

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

tables = spark.sql(f"SHOW TABLES IN `{catalog}`.`{schema}`").collect()
print(f"\n  Tables in {schema}:")
for row in tables:
    print(f"    - {row.tableName}")

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

# DBTITLE 1,Seed claims_history table with historical settlements
spark.sql(f"""
    CREATE TABLE IF NOT EXISTS `{catalog}`.`{schema}`.`claims_history` (
        historical_claim_id STRING,
        diagnosis_icd STRING,
        settled_amount DOUBLE
    ) USING delta
""")

history_count = spark.sql(f"SELECT count(*) FROM `{catalog}`.`{schema}`.`claims_history`").collect()[0][0]
if history_count == 0:
    import random
    diagnoses_seed = [
        ("K35.80", 60000), ("A90", 25000), ("Z96.65", 250000), ("H25.9", 35000),
        ("J12.9", 50000), ("I25.10", 180000), ("K40.90", 45000), ("S72.009A", 70000),
        ("A01.0", 20000), ("K80.20", 55000)
    ]
    history_data = []
    for idx in range(1000):
        diag_code, base_amt = random.choice(diagnoses_seed)
        settled_amt = float(base_amt * random.uniform(0.85, 1.15))
        history_data.append({
            "historical_claim_id": f"HIST-CLM-{idx:05d}",
            "diagnosis_icd": diag_code,
            "settled_amount": settled_amt
        })
    spark.createDataFrame(history_data).write.format("delta").mode("overwrite").saveAsTable(f"`{catalog}`.`{schema}`.`claims_history`")
    print("✓ Seeded claims_history table with synthetic historical claims")

print("\nRun notebooks in this order next: 01 → 02 → 03 → 04 → 05 → 06 → 07")