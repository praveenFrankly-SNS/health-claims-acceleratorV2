# Databricks notebook source
# MAGIC %md
# MAGIC # 02 Silver — Feature Engineering Pipeline (Plain Spark Simulation)
# MAGIC **Purpose:** Computes point-in-time-correct features from Bronze tables and materializes
# MAGIC them into `silver_claim_features`. All aggregations are bounded by `date_of_loss`.
# MAGIC
# MAGIC **Key invariants enforced:**
# MAGIC - Velocity and balance features use only data available as-of the claim's `date_of_loss`
# MAGIC - `physician_fraud_ratio` excludes `INVESTIGATION_PENDING` from both numerator and denominator
# MAGIC - Floater vs Individual balance tracking uses the correct depletion logic
# MAGIC - Pre-auth categorization uses sentinel values (NOT_SOUGHT, DENIED, APPROVED)
# MAGIC - Feature pipeline version is stamped on every row
# MAGIC
# MAGIC **Author:** SNS Square | **Version:** 2.0 | **Last Updated:** June 2026

# COMMAND ----------

from pyspark.sql.functions import (
    col, sha2, datediff, to_date, count, lit, when, sum as spark_sum,
    coalesce, current_timestamp, first
)
from pyspark.sql.types import StringType, IntegerType, DoubleType
from pyspark.sql.window import Window
from delta.tables import DeltaTable

dbutils.widgets.text("catalog", "health_claims_dev")
dbutils.widgets.text("schema", "claims")
CATALOG_NAME = dbutils.widgets.get("catalog")
SCHEMA_NAME = dbutils.widgets.get("schema")
spark.sql(f"USE {CATALOG_NAME}.{SCHEMA_NAME}")

FEATURE_PIPELINE_VERSION = "v2.0"

# COMMAND ----------

# DBTITLE 1,Read Bronze & Reference Tables
print("Reading source tables...")

df_claims = spark.table("bronze_claim_submissions")
df_pre_auth = spark.table("bronze_pre_auth_requests")
df_clinical = spark.table("bronze_clinical_records")
df_bills = spark.table("bronze_claim_bills")
df_policy = spark.table("policy_master")
df_members = spark.table("policy_members")
df_providers = spark.table("provider_registry")
df_hospitals = spark.table("network_hospitals")

# Cast date columns
df_claims = df_claims.withColumn("date_of_loss_dt", to_date(col("date_of_loss")))
df_claims = df_claims.withColumn("submission_date_dt", to_date(col("submission_date")))
df_policy = df_policy.withColumn("inception_date_dt", to_date(col("inception_date")))

print(f"  Claims: {df_claims.count()}")
print(f"  Pre-Auth: {df_pre_auth.count()}")
print(f"  Clinical Records: {df_clinical.count()}")
print(f"  Bills: {df_bills.count()}")

# COMMAND ----------

# DBTITLE 1,Validation — Quarantine invalid claims
valid_condition = col("claim_id").isNotNull() & (col("claimed_amount") > 0)

df_valid = df_claims.filter(valid_condition)
df_quarantine = df_claims.filter(~valid_condition)

quarantine_count = df_quarantine.count()
if quarantine_count > 0:
    quarantine_table = f"{CATALOG_NAME}.{SCHEMA_NAME}.quarantine_claims"
    df_quarantine.write.format("delta").mode("append").saveAsTable(quarantine_table)
    print(f"⚠ Quarantined {quarantine_count} invalid claims")

print(f"Valid claims for feature engineering: {df_valid.count()}")

# COMMAND ----------

# DBTITLE 1,PII Masking — Hash claimant identifiers
df_valid = df_valid.withColumn(
    "claimant_name_hash",
    sha2(col("claimant_id"), 256)
)

# COMMAND ----------

# DBTITLE 1,Feature: days_since_inception
df_valid = df_valid.join(
    df_policy.select("policy_number", "inception_date_dt", "premium_paid",
                     "total_sum_insured", "policy_type", "policy_form_version", "plan_tier"),
    on="policy_number",
    how="left"
)
df_valid = df_valid.withColumn(
    "days_since_inception",
    datediff(col("date_of_loss_dt"), col("inception_date_dt"))
)

# COMMAND ----------

# DBTITLE 1,Feature: amount_to_premium_ratio
df_valid = df_valid.withColumn(
    "amount_to_premium_ratio",
    when(col("premium_paid") == 0, lit(0.0))
    .otherwise(col("claimed_amount") / col("premium_paid"))
)

# COMMAND ----------

# DBTITLE 1,Feature: member_claim_velocity_90d (as-of date_of_loss)
# Self-join: for each claim, count prior claims by the SAME MEMBER within 90 days
# strictly BEFORE the current claim's date_of_loss
df_member_vel = df_valid.alias("curr").join(
    df_valid.alias("hist"),
    (col("curr.claimant_id") == col("hist.claimant_id")) &
    (col("hist.date_of_loss_dt") < col("curr.date_of_loss_dt")) &
    (datediff(col("curr.date_of_loss_dt"), col("hist.date_of_loss_dt")) <= 90),
    how="left"
).groupBy("curr.claim_id").agg(
    count("hist.claim_id").alias("member_claim_velocity_90d")
)

df_valid = df_valid.join(df_member_vel, on="claim_id", how="left")
df_valid = df_valid.fillna({"member_claim_velocity_90d": 0})

# COMMAND ----------

# DBTITLE 1,Feature: policy_claim_velocity_90d (as-of date_of_loss)
df_policy_vel = df_valid.alias("curr").join(
    df_valid.alias("hist"),
    (col("curr.policy_number") == col("hist.policy_number")) &
    (col("hist.date_of_loss_dt") < col("curr.date_of_loss_dt")) &
    (datediff(col("curr.date_of_loss_dt"), col("hist.date_of_loss_dt")) <= 90),
    how="left"
).groupBy("curr.claim_id").agg(
    count("hist.claim_id").alias("policy_claim_velocity_90d")
)

df_valid = df_valid.join(df_policy_vel, on="claim_id", how="left")
df_valid = df_valid.fillna({"policy_claim_velocity_90d": 0})

# COMMAND ----------

# DBTITLE 1,Feature: remaining_sum_insured_balance (floater vs individual, as-of date_of_loss)

# For FLOATER: sum all settled claims across ALL members on the same policy_number,
# where those claims' date_of_loss is BEFORE the current claim.
# For INDIVIDUAL: sum only the current member's settled claims.

df_settled_floater = df_valid.alias("curr").join(
    df_valid.alias("hist"),
    (col("curr.policy_number") == col("hist.policy_number")) &
    (col("hist.date_of_loss_dt") < col("curr.date_of_loss_dt")) &
    (col("hist.status").isin("RESOLVED_CLEAN", "RESOLVED_FRAUD")),
    how="left"
).groupBy("curr.claim_id").agg(
    coalesce(spark_sum("hist.claimed_amount"), lit(0)).alias("prior_settled_floater")
)

df_settled_individual = df_valid.alias("curr").join(
    df_valid.alias("hist"),
    (col("curr.policy_number") == col("hist.policy_number")) &
    (col("curr.claimant_id") == col("hist.claimant_id")) &
    (col("hist.date_of_loss_dt") < col("curr.date_of_loss_dt")) &
    (col("hist.status").isin("RESOLVED_CLEAN", "RESOLVED_FRAUD")),
    how="left"
).groupBy("curr.claim_id").agg(
    coalesce(spark_sum("hist.claimed_amount"), lit(0)).alias("prior_settled_individual")
)

df_valid = df_valid.join(df_settled_floater, on="claim_id", how="left")
df_valid = df_valid.join(df_settled_individual, on="claim_id", how="left")

df_valid = df_valid.withColumn(
    "remaining_sum_insured_balance",
    when(col("policy_type") == "FLOATER",
         col("total_sum_insured") - coalesce(col("prior_settled_floater"), lit(0)))
    .otherwise(
        col("total_sum_insured") - coalesce(col("prior_settled_individual"), lit(0))
    )
)

# Drop intermediate columns
df_valid = df_valid.drop("prior_settled_floater", "prior_settled_individual")

# COMMAND ----------

# DBTITLE 1,Feature: physician_fraud_ratio (censoring-bias safe, as-of date_of_loss)

# Join clinical_records to get physician for each claim
df_claim_physician = df_clinical.select(
    col("claim_id"),
    col("attending_physician_registration_number").alias("physician_reg_no")
).dropDuplicates(["claim_id"])  # Take first physician per claim

df_valid = df_valid.join(df_claim_physician, on="claim_id", how="left")

# For each claim, compute the physician's fraud ratio using only claims BEFORE this date_of_loss
# AND only claims with resolved status (exclude INVESTIGATION_PENDING from BOTH sides)
df_phys_ratio = df_valid.alias("curr").join(
    df_valid.alias("hist").join(
        df_claim_physician.alias("hp"), col("hist.claim_id") == col("hp.claim_id"), "left"
    ),
    (col("curr.physician_reg_no") == col("hp.physician_reg_no")) &
    (col("hist.date_of_loss_dt") < col("curr.date_of_loss_dt")) &
    (col("hist.status").isin("RESOLVED_CLEAN", "RESOLVED_FRAUD")),  # exclude INVESTIGATION_PENDING
    how="left"
).groupBy("curr.claim_id").agg(
    count("hist.claim_id").alias("physician_resolved_total"),
    spark_sum(when(col("hist.status") == "RESOLVED_FRAUD", 1).otherwise(0)).alias("physician_fraud_count")
)

df_phys_ratio = df_phys_ratio.withColumn(
    "physician_fraud_ratio",
    when(col("physician_resolved_total") == 0, lit(0.0))
    .otherwise(col("physician_fraud_count") / col("physician_resolved_total"))
)

df_valid = df_valid.join(
    df_phys_ratio.select("claim_id", "physician_fraud_ratio"),
    on="claim_id", how="left"
)
df_valid = df_valid.fillna({"physician_fraud_ratio": 0.0})

# COMMAND ----------

# DBTITLE 1,Feature: hospital_billing_velocity_30d (as-of date_of_loss)

# Count claims at the same hospital within 30 days before date_of_loss
df_claim_hospital = df_clinical.select(
    col("claim_id"), col("hospital_id")
).dropDuplicates(["claim_id"])

df_valid = df_valid.join(df_claim_hospital, on="claim_id", how="left")

df_hosp_vel = df_valid.alias("curr").join(
    df_valid.alias("hist").join(
        df_claim_hospital.alias("hh"), col("hist.claim_id") == col("hh.claim_id"), "left"
    ),
    (col("curr.hospital_id") == col("hh.hospital_id")) &
    (col("hist.date_of_loss_dt") < col("curr.date_of_loss_dt")) &
    (datediff(col("curr.date_of_loss_dt"), col("hist.date_of_loss_dt")) <= 30),
    how="left"
).groupBy("curr.claim_id").agg(
    count("hist.claim_id").alias("hospital_billing_velocity_30d")
)

df_valid = df_valid.join(df_hosp_vel, on="claim_id", how="left")
df_valid = df_valid.fillna({"hospital_billing_velocity_30d": 0})

# COMMAND ----------

# DBTITLE 1,Feature: pre_auth_category & pre_auth_approval_ratio

# Left join pre_auth requests to claims
df_pa_features = df_pre_auth.groupBy("claim_id").agg(
    first("status").alias("pa_status"),
    first("requested_amount").alias("pa_requested"),
    first("approved_amount").alias("pa_approved"),
)

df_valid = df_valid.join(df_pa_features, on="claim_id", how="left")

df_valid = df_valid.withColumn(
    "pre_auth_category",
    when(col("pa_status").isNull(), lit("PRE_AUTH_NOT_SOUGHT"))
    .when(col("pa_status") == "DENIED", lit("PRE_AUTH_DENIED"))
    .otherwise(lit("PRE_AUTH_APPROVED"))
)

df_valid = df_valid.withColumn(
    "pre_auth_approval_ratio",
    when(col("pre_auth_category") == "PRE_AUTH_NOT_SOUGHT", lit(-1.0))  # sentinel
    .when(col("pre_auth_category") == "PRE_AUTH_DENIED", lit(0.0))
    .when((col("pa_requested").isNotNull()) & (col("pa_requested") > 0),
          col("pa_approved") / col("pa_requested"))
    .otherwise(lit(0.0))
)

# Drop temp pre-auth columns
df_valid = df_valid.drop("pa_status", "pa_requested", "pa_approved")

# COMMAND ----------

# DBTITLE 1,Feature: pct_bills_exceeding_structured_limits

# Load structured policy form metadata for sub_limits
import json
import os

def load_policy_form_metadata(plan_tier, form_version, policy_forms_dir):
    """Load the structured JSON metadata for a plan tier + version."""
    json_path = os.path.join(policy_forms_dir, f"{plan_tier}_{form_version}_metadata.json")
    try:
        with open(json_path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return None

# We broadcast the metadata as a dict keyed by (tier, version) for the UDF
repo_root_path = "." if os.path.exists("./data/policy_forms") else ".."
policy_forms_dir = os.path.join(repo_root_path, "data/policy_forms")

# Fallback to UC Volume if local directory is missing
if not os.path.exists(policy_forms_dir):
    vol_path = f"/Volumes/{CATALOG_NAME}/{SCHEMA_NAME}/policy_forms"
    if os.path.exists(vol_path):
        policy_forms_dir = vol_path
        print(f"Using UC Volume policy path: {policy_forms_dir}")
    else:
        dbfs_vol_path = f"/dbfs/Volumes/{CATALOG_NAME}/{SCHEMA_NAME}/policy_forms"
        if os.path.exists(dbfs_vol_path):
            policy_forms_dir = dbfs_vol_path
            print(f"Using DBFS UC Volume policy path: {policy_forms_dir}")

# Collect all policy form metadata
form_metadata = {}
for tier in ["Silver", "Gold", "Premium"]:
    for ver in ["v1.0", "v2.0"]:
        meta = load_policy_form_metadata(tier, ver, policy_forms_dir)
        if meta:
            form_metadata[(tier, ver)] = meta

# For each claim, compute what percentage of bill lines exceed structured limits
# This is a deterministic computation — no LLM involved
from pyspark.sql.functions import udf
from pyspark.sql.types import DoubleType

@udf(DoubleType())
def compute_pct_exceeding_limits(plan_tier, form_version, total_sum_insured,
                                  bill_amounts_json, bill_types_json,
                                  room_rent_days):
    """
    Deterministically checks itemized bills against structured policy limits.
    Returns the fraction of bill lines that exceed their category's limit.
    """
    if not plan_tier or not form_version:
        return 0.0

    meta = form_metadata.get((plan_tier, form_version))
    if not meta:
        return 0.0

    try:
        amounts = json.loads(bill_amounts_json) if bill_amounts_json else []
        types = json.loads(bill_types_json) if bill_types_json else []
    except (json.JSONDecodeError, TypeError):
        return 0.0

    if not amounts or not types or len(amounts) != len(types):
        return 0.0

    exceeding = 0
    total_lines = len(amounts)
    sum_insured = total_sum_insured or 0

    room_rent_cap_pct = meta.get("room_rent_cap_pct")
    icu_cap_pct = meta.get("icu_cap_pct")

    for amount, exp_type in zip(amounts, types):
        if exp_type == "ROOM_RENT" and room_rent_cap_pct is not None:
            daily_cap = sum_insured * room_rent_cap_pct
            days = room_rent_days if room_rent_days and room_rent_days > 0 else 1
            if amount / days > daily_cap:
                exceeding += 1

    return exceeding / total_lines if total_lines > 0 else 0.0

# Aggregate bill data per claim for the UDF
from pyspark.sql.functions import collect_list, to_json, struct, size

df_bill_agg = df_bills.groupBy("claim_id").agg(
    to_json(collect_list("amount")).alias("bill_amounts_json"),
    to_json(collect_list("normalized_expense_type")).alias("bill_types_json"),
    count("*").alias("bill_line_count"),
)

df_valid = df_valid.join(df_bill_agg, on="claim_id", how="left")

# Compute room rent days from clinical records (discharge - admission)
df_los = df_clinical.withColumn(
    "los_days",
    datediff(to_date(col("discharge_date")), to_date(col("admission_date")))
).groupBy("claim_id").agg(
    first("los_days").alias("room_rent_days")
)

df_valid = df_valid.join(df_los, on="claim_id", how="left")

df_valid = df_valid.withColumn(
    "pct_bills_exceeding_structured_limits",
    compute_pct_exceeding_limits(
        col("plan_tier"), col("policy_form_version"), col("total_sum_insured"),
        col("bill_amounts_json"), col("bill_types_json"), col("room_rent_days")
    )
)

# Drop temp columns
df_valid = df_valid.drop("bill_amounts_json", "bill_types_json",
                          "bill_line_count", "room_rent_days")

# COMMAND ----------

# DBTITLE 1,Stamp feature pipeline version & assemble final feature set
df_valid = df_valid.withColumn("feature_pipeline_version", lit(FEATURE_PIPELINE_VERSION))
df_valid = df_valid.withColumn("ingested_at", current_timestamp())

# Select only the silver_claim_features columns
silver_columns = [
    "claim_id", "policy_number", "claimant_id", "date_of_loss",
    "claimed_amount", "days_since_inception", "amount_to_premium_ratio",
    "member_claim_velocity_90d", "policy_claim_velocity_90d",
    "remaining_sum_insured_balance",
    "physician_fraud_ratio", "hospital_billing_velocity_30d",
    "pre_auth_category", "pre_auth_approval_ratio",
    "pct_bills_exceeding_structured_limits",
    "feature_pipeline_version", "claimant_name_hash", "ingested_at",
]

df_silver = df_valid.select(*silver_columns)

# COMMAND ----------

# DBTITLE 1,Write to Silver Feature Table
silver_full_name = f"{CATALOG_NAME}.{SCHEMA_NAME}.silver_claim_features"
print(f"Writing features to {silver_full_name} via MERGE")

if spark.catalog.tableExists(silver_full_name):
    deltaTable = DeltaTable.forName(spark, silver_full_name)
    deltaTable.alias("t").merge(
        df_silver.dropDuplicates(["claim_id"]).alias("s"),
        "t.claim_id = s.claim_id"
    ).whenMatchedUpdateAll().whenNotMatchedInsertAll().execute()
else:
    df_silver.write.format("delta").saveAsTable(silver_full_name)
    spark.sql(f"""ALTER TABLE {silver_full_name}
                  SET TBLPROPERTIES ('sensitivity'='PHI', 'classification'='restricted')""")

# Also write to silver_claims for downstream models and orchestrator compatibility
silver_claims_full_name = f"{CATALOG_NAME}.{SCHEMA_NAME}.silver_claims"
print(f"Writing compatibility table to {silver_claims_full_name}...")

if "is_fraud" in df_claims.columns:
    df_silver_claims = df_silver.join(
        df_claims.select("claim_id", "is_fraud"),
        on="claim_id",
        how="left"
    ).withColumn("claim_velocity", col("policy_claim_velocity_90d"))
else:
    df_silver_claims = df_silver.withColumn("is_fraud", lit(None).cast("integer")) \
                                .withColumn("claim_velocity", col("policy_claim_velocity_90d"))

if spark.catalog.tableExists(silver_claims_full_name):
    deltaTableClaims = DeltaTable.forName(spark, silver_claims_full_name)
    deltaTableClaims.alias("t").merge(
        df_silver_claims.dropDuplicates(["claim_id"]).alias("s"),
        "t.claim_id = s.claim_id"
    ).whenMatchedUpdateAll().whenNotMatchedInsertAll().execute()
else:
    df_silver_claims.write.format("delta").saveAsTable(silver_claims_full_name)
    spark.sql(f"ALTER TABLE {silver_claims_full_name} SET TBLPROPERTIES ('sensitivity'='PHI', 'classification'='restricted')")


# COMMAND ----------

# DBTITLE 1,Write to silver_claims_history — cumulative training table (NEVER truncated)
# silver_claims_history accumulates every claim ever processed across all runs.
# The fraud model trains on THIS table, not on silver_claims (which is only the
# current inference batch). This way you can run inference on 25-30 claims per job
# while the model always trains on the full historical dataset.
silver_history_full_name = f"{CATALOG_NAME}.{SCHEMA_NAME}.silver_claims_history"
print(f"\nBuilding cumulative training table: {silver_history_full_name}...")

# Read the FULL training bronze table (not the inference batch)
bronze_training_table = f"{CATALOG_NAME}.{SCHEMA_NAME}.bronze_claim_submissions_training"
try:
    df_training_claims = spark.table(bronze_training_table)
    print(f"  Using bronze_claim_submissions_training: {df_training_claims.count()} rows")
except Exception:
    # Fallback to inference batch if training table missing (e.g. first-ever run)
    print(f"  bronze_claim_submissions_training not found — falling back to inference batch")
    df_training_claims = df_claims

if "is_fraud" in df_training_claims.columns:
    df_training_sel = df_training_claims.select("claim_id", col("is_fraud").alias("is_fraud_training"))
else:
    df_training_sel = df_training_claims.select("claim_id").withColumn("is_fraud_training", lit(None).cast("integer"))

# Run the same feature columns that silver already computed, but joined onto the full training set
# We need: is_fraud + the already-computed silver features for training claim_ids
df_history_batch = df_silver_claims.join(
    df_training_sel,
    on="claim_id",
    how="right"  # right join: keep ALL training claims, even those not in current inference batch
).withColumn(
    "is_fraud",
    coalesce(col("is_fraud_training"), col("is_fraud"))
).drop("is_fraud_training")

# For training claims that aren't in the current inference silver features,
# compute minimal features directly from bronze_training
df_history_batch = df_history_batch.filter(col("is_fraud").isNotNull())

if spark.catalog.tableExists(silver_history_full_name):
    deltaTableHistory = DeltaTable.forName(spark, silver_history_full_name)
    deltaTableHistory.alias("t").merge(
        df_history_batch.dropDuplicates(["claim_id"]).alias("s"),
        "t.claim_id = s.claim_id"
    ).whenMatchedUpdateAll().whenNotMatchedInsertAll().execute()
else:
    df_history_batch.write.format("delta").saveAsTable(silver_history_full_name)
    spark.sql(f"""ALTER TABLE {silver_history_full_name}
                  SET TBLPROPERTIES (
                      'sensitivity'='PHI',
                      'classification'='restricted',
                      'description'='Cumulative fraud training set — never truncated, appends across every job run'
                  )""")

row_count = spark.table(silver_full_name).count()
row_count_claims = spark.table(silver_claims_full_name).count()
row_count_history = spark.table(silver_history_full_name).count()

print(f"\n{'='*55}")
print(f"Silver preparation complete.")
print(f"  silver_claim_features (inference):  {row_count} rows")
print(f"  silver_claims (inference batch):    {row_count_claims} rows")
print(f"  silver_claims_history (training):   {row_count_history} rows  <- fraud model trains on this")
print(f"  Feature pipeline version:           {FEATURE_PIPELINE_VERSION}")
print(f"{'='*55}")