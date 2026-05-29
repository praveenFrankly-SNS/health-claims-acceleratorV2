# Databricks notebook source
# MAGIC %md
# MAGIC # 02 Silver — Delta Live Tables Simulation (Plain Spark)
# MAGIC **Purpose:** Cleans, validates, and standardizes Bronze data using plain Spark.
# MAGIC **Note:** This is a plain Spark simulation of Delta Live Tables (DLT) designed to run on the Databricks Free Edition. For the production DLT pipeline using decorators, refer to `02_silver_dlt_real.py`.
# MAGIC **Author:** SNS Square | **Version:** 1.0 | **Last Updated:** May 2026

# COMMAND ----------

from pyspark.sql.functions import col, sha2, datediff, to_date, count, lit, when
from pyspark.sql.window import Window
from delta.tables import DeltaTable

dbutils.widgets.text("catalog", "health_claims_dev")
dbutils.widgets.text("schema", "claims")
CATALOG_NAME = dbutils.widgets.get("catalog")
SCHEMA_NAME = dbutils.widgets.get("schema")
spark.sql(f"USE {CATALOG_NAME}.{SCHEMA_NAME}")

bronze_table = "bronze_claims"
silver_table = "silver_claims"
quarantine_table = "quarantine_claims"
policy_master_table = "policy_master"
claims_history_table = "claims_history"

# COMMAND ----------

print(f"Reading from {bronze_table}")
df_bronze = spark.table(bronze_table)

# Validation rules (Simulated DLT expectations)
# 1. claim_id must not be null
# 2. claimed_amount must be > 0

valid_condition = col("claim_id").isNotNull() & (col("claimed_amount") > 0)

# Split into valid and quarantine
df_valid = df_bronze.filter(valid_condition)
df_quarantine = df_bronze.filter(~valid_condition)

# COMMAND ----------

# PII Masking & Feature Engineering for Valid Claims

# Hash PII (claimant_name) and DROP original plaintext column
df_valid = df_valid.withColumn("claimant_name_hash", sha2(col("claimant_name"), 256)).drop("claimant_name")
df_quarantine = df_quarantine.withColumn("claimant_name_hash", sha2(col("claimant_name"), 256)).drop("claimant_name")

# Read Gold tables for feature computation
try:
    df_policy = spark.table(policy_master_table).select("policy_number", "inception_date", "premium_paid", "sum_insured")
    df_history = spark.table(claims_history_table).select("policy_number", "claim_date")
    
    # 1. Compute days_since_inception
    df_valid = df_valid.join(df_policy, on="policy_number", how="left")
    df_valid = df_valid.withColumn("date_of_loss_dt", to_date(col("date_of_loss")))
    df_valid = df_valid.withColumn("inception_date_dt", to_date(col("inception_date")))
    df_valid = df_valid.withColumn("days_since_inception", datediff(col("date_of_loss_dt"), col("inception_date_dt")))
    
    # Compute amount_to_premium_ratio
    df_valid = df_valid.withColumn("amount_to_premium_ratio", col("claimed_amount") / col("premium_paid"))
    df_valid = df_valid.withColumn("amount_to_premium_ratio", when(col("premium_paid") == 0, 0).otherwise(col("amount_to_premium_ratio")))
    
    # 2. Compute claim_velocity (number of prior claims in the last 90 days)
    # We join current claims with history, keeping history claims within 90 days prior to date_of_loss
    df_recent_history = df_valid.alias("v").join(
        df_history.alias("h"),
        on="policy_number",
        how="left"
    ).filter(
        (to_date(col("h.claim_date")) >= to_date(col("v.date_of_loss_dt")) - lit(90)) &
        (to_date(col("h.claim_date")) < to_date(col("v.date_of_loss_dt")))
    ).groupBy("v.claim_id").agg(count("h.claim_date").alias("claim_velocity"))
    
    df_valid = df_valid.join(df_recent_history, on="claim_id", how="left")
    df_valid = df_valid.fillna({"claim_velocity": 0})
    
    # Drop temp columns
    df_valid = df_valid.drop("date_of_loss_dt", "inception_date_dt")

except Exception as e:
    print(f"Warning: Could not compute ML features. Make sure {policy_master_table} and {claims_history_table} exist. Error: {e}")
    df_valid = df_valid.withColumn("days_since_inception", lit(0))
    df_valid = df_valid.withColumn("amount_to_premium_ratio", lit(0.0))
    df_valid = df_valid.withColumn("claim_velocity", lit(0))

# COMMAND ----------

# Write to Silver Table
silver_full_name = f"{CATALOG_NAME}.{SCHEMA_NAME}.{silver_table}"
print(f"Writing valid claims to {silver_full_name} via MERGE")
if spark.catalog.tableExists(silver_full_name):
    try:
        spark.sql(f"ALTER TABLE {silver_full_name} SET TBLPROPERTIES ('delta.columnMapping.mode' = 'name')")
        spark.sql(f"ALTER TABLE {silver_full_name} DROP COLUMN IF EXISTS claimant_name")
    except Exception as e:
        print(f"Notice: Could not drop claimant_name from target table: {e}")
    deltaTable = DeltaTable.forName(spark, silver_full_name)
    deltaTable.alias("t").merge(
        df_valid.dropDuplicates(["claim_id"]).alias("s"),
        "t.claim_id = s.claim_id"
    ).whenMatchedUpdateAll().whenNotMatchedInsertAll().execute()
else:
    df_valid.write.format("delta").saveAsTable(silver_full_name)
    spark.sql(f"ALTER TABLE {silver_full_name} SET TBLPROPERTIES ('sensitivity'='PHI', 'classification'='restricted')")

# Write to Quarantine Table
quarantine_full_name = f"{CATALOG_NAME}.{SCHEMA_NAME}.{quarantine_table}"
print(f"Writing invalid claims to {quarantine_full_name} via MERGE")
if spark.catalog.tableExists(quarantine_full_name):
    try:
        spark.sql(f"ALTER TABLE {quarantine_full_name} SET TBLPROPERTIES ('delta.columnMapping.mode' = 'name')")
        spark.sql(f"ALTER TABLE {quarantine_full_name} DROP COLUMN IF EXISTS claimant_name")
    except Exception as e:
        print(f"Notice: Could not drop claimant_name from target table: {e}")
        
    deltaTable = DeltaTable.forName(spark, quarantine_full_name)
    deltaTable.alias("t").merge(
        df_quarantine.dropDuplicates(["claim_id"]).alias("s"),
        "t.claim_id = s.claim_id"
    ).whenMatchedUpdateAll().whenNotMatchedInsertAll().execute()
else:
    df_quarantine.write.format("delta").saveAsTable(quarantine_full_name)
    spark.sql(f"ALTER TABLE {quarantine_full_name} SET TBLPROPERTIES ('sensitivity'='PHI', 'classification'='restricted')")

print(f"Silver preparation complete. Valid: {df_valid.count()}, Quarantined: {df_quarantine.count()}")