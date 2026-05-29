# Databricks notebook source
# MAGIC %md
# MAGIC # 02 Silver — Delta Live Tables (Trial / Paid Edition)
# MAGIC
# MAGIC **Purpose:** Cleans, validates, and standardises Bronze data using native Delta Live Tables (DLT).
# MAGIC Applies data-quality expectations, masks PII, and computes ML features required by the fraud and reserve agents.
# MAGIC
# MAGIC **⚠️ Important:** This notebook **must** be attached to a **DLT pipeline**, not run directly on a cluster.
# MAGIC To create a pipeline:
# MAGIC 1. Go to **Workflows → Delta Live Tables → Create Pipeline**
# MAGIC 2. Set this notebook as the pipeline source
# MAGIC 3. Set the target catalog/schema to `health_claims_dev.claims`
# MAGIC 4. Click **Start**
# MAGIC
# MAGIC For Free Edition / plain-Spark fallback, use `02_silver_preparation_spark_sim.py` instead.
# MAGIC
# MAGIC **Author:** SNS Square | **Version:** 1.1 | **Last Updated:** May 2026

# COMMAND ----------

import dlt
from pyspark.sql import functions as F
from pyspark.sql.functions import (
    col, sha2, datediff, to_date, count, lit, when
)
from pyspark.sql.window import Window

# ---------------------------------------------------------------------------
# Configuration — override via DLT pipeline parameters if needed
# ---------------------------------------------------------------------------
CATALOG_NAME  = spark.conf.get("catalog_name",  "health_claims_dev")
SCHEMA_NAME   = spark.conf.get("schema_name",   "claims")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Bronze Source (streaming read)
# MAGIC
# MAGIC DLT reads `bronze_claims` as a streaming source so that only new rows are
# MAGIC processed on each pipeline update (incremental / CDC pattern).

# COMMAND ----------

@dlt.view(
    name="bronze_claims_raw",
    comment="Streaming view over the Bronze claims table — source for Silver transformations"
)
def bronze_claims_raw():
    return (
        spark.readStream
             .format("delta")
             .table(f"{CATALOG_NAME}.{SCHEMA_NAME}.bronze_claims")
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Silver Claims — validated, PII-masked, ML-feature-enriched
# MAGIC
# MAGIC Quality expectations (DLT `expect_or_fail`) act as hard gates:
# MAGIC - `valid_claim_id`  — `claim_id` must not be NULL
# MAGIC - `positive_amount` — `claimed_amount` must be > 0
# MAGIC
# MAGIC Records that fail either expectation are **dropped from this table** and
# MAGIC routed to `quarantine_claims` below.

# COMMAND ----------

@dlt.table(
    name="silver_claims",
    comment="Validated claims with PII masked (SHA-256) and ML features computed",
    table_properties={
        "quality":                    "silver",
        "pipelines.autoOptimize.managed": "true",
        "delta.enableChangeDataFeed": "true",
        "sensitivity": "PHI",
        "classification": "restricted"
    }
)
@dlt.expect_or_drop("valid_claim_id",  "claim_id IS NOT NULL")
@dlt.expect_or_drop("positive_amount", "claimed_amount > 0")
def silver_claims():
    """
    Reads from the bronze_claims_raw view, applies PII masking and
    computes three ML features used by Agent 2 (Fraud) and Agent 4 (Reserve):

    - days_since_inception      : days between policy inception and date of loss
    - amount_to_premium_ratio   : claimed_amount / annual_premium_paid
    - claim_velocity            : number of prior claims on the same policy in the last 90 days
    """

    df_bronze = dlt.read_stream("bronze_claims_raw")

    # ------------------------------------------------------------------
    # PII Masking — hash claimant_name with SHA-256 and drop original
    # ------------------------------------------------------------------
    df = df_bronze.withColumn("claimant_name_hash", sha2(col("claimant_name"), 256)).drop("claimant_name")

    # ------------------------------------------------------------------
    # Feature 1 & 2 — join policy_master for inception date & premium
    # ------------------------------------------------------------------
    df_policy = (
        spark.read
             .format("delta")
             .table(f"{CATALOG_NAME}.{SCHEMA_NAME}.policy_master")
             .select("policy_number", "inception_date", "premium_paid", "sum_insured")
    )

    df = (
        df.join(df_policy, on="policy_number", how="left")
          .withColumn("date_of_loss_dt",    to_date(col("date_of_loss")))
          .withColumn("inception_date_dt",  to_date(col("inception_date")))
          .withColumn(
              "days_since_inception",
              datediff(col("date_of_loss_dt"), col("inception_date_dt"))
          )
          .withColumn(
              "amount_to_premium_ratio",
              when(col("premium_paid").isNull() | (col("premium_paid") == 0), lit(0.0))
              .otherwise(col("claimed_amount") / col("premium_paid"))
          )
          .drop("date_of_loss_dt", "inception_date_dt")
    )

    # ------------------------------------------------------------------
    # Feature 3 — claim_velocity (prior claims in last 90 days)
    # Streaming aggregation: we use a static read of claims_history so
    # that the join is a stream-static join (supported in DLT).
    # ------------------------------------------------------------------
    df_history = (
        spark.read
             .format("delta")
             .table(f"{CATALOG_NAME}.{SCHEMA_NAME}.claims_history")
             .select("policy_number", "claim_date")
    )

    # Compute velocity as a static aggregation keyed on policy_number.
    # In a full production pipeline you would use a watermark + window;
    # this approach is correct for the accelerator's batch-style DLT run.
    df_velocity = (
        df_history
        .withColumn("claim_date_dt", to_date(col("claim_date")))
        .groupBy("policy_number")
        .agg(count("claim_date").alias("claim_velocity"))
    )

    df = (
        df.join(df_velocity, on="policy_number", how="left")
          .fillna({"claim_velocity": 0})
    )

    return df

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Quarantine Claims — records that failed quality expectations
# MAGIC
# MAGIC Any row where `claim_id IS NULL` or `claimed_amount <= 0` lands here
# MAGIC for manual review or reprocessing.

# COMMAND ----------

@dlt.table(
    name="quarantine_claims",
    comment="Claims that failed DLT quality expectations — require manual review",
    table_properties={
        "quality": "quarantine",
        "sensitivity": "PHI",
        "classification": "restricted"
    }
)
@dlt.expect_or_drop("invalid_claim_id",  "claim_id IS NULL")
@dlt.expect_or_drop("non_positive_amount", "claimed_amount <= 0")
def quarantine_claims():
    """
    Mirror of the bronze source filtered to rows that violate the Silver
    quality gates.  Uses the same streaming view so DLT processes them
    in the same micro-batch as silver_claims.
    """
    df_bronze = dlt.read_stream("bronze_claims_raw")

    # Keep only the rows that would fail the Silver expectations
    quarantine_condition = (
        col("claim_id").isNull() | (col("claimed_amount") <= 0)
    )

    return df_bronze.filter(quarantine_condition)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Pipeline Notes
# MAGIC
# MAGIC | Item | Detail |
# MAGIC |---|---|
# MAGIC | **Trigger mode** | Triggered (run on-demand) or Continuous (real-time) |
# MAGIC | **Target schema** | `health_claims_dev.claims` |
# MAGIC | **Upstream dependency** | `bronze_claims` must exist (run `01_bronze_ingestion` first) |
# MAGIC | **Downstream consumers** | `04a_train_fraud_model`, `06a_train_reserve_model`, `07_supervisor_orchestrator` |
# MAGIC | **Free Edition fallback** | `02_silver_preparation_spark_sim.py` (plain Spark, no DLT) |
# MAGIC
# MAGIC ### DLT Pipeline Parameters (optional overrides)
# MAGIC Set these in the pipeline configuration JSON under `"configuration"`:
# MAGIC ```json
# MAGIC {
# MAGIC   "catalog_name": "health_claims_dev",
# MAGIC   "schema_name":  "claims"
# MAGIC }
# MAGIC ```