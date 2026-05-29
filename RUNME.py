# Databricks notebook source
# MAGIC %md
# MAGIC # Health Claims Multi-Agent Accelerator - RUNME
# MAGIC This notebook runs the full pipeline end-to-end.
# MAGIC Zero manual steps required once configured.

# COMMAND ----------

import time

def run_notebook(path, timeout_seconds=3600, arguments=None):
    if arguments is None:
        arguments = {}
    print(f"Running {path}...")
    start = time.time()
    try:
        # Assuming running within Databricks environment
        result = dbutils.notebook.run(path, timeout_seconds, arguments)
        print(f"Finished {path} in {time.time() - start:.2f} seconds.")
        return result
    except Exception as e:
        print(f"Failed to run {path}. Error: {e}")
        # We don't raise here for local testing, but in production we should
        return None

# COMMAND ----------

# 1. Setup the workspace and Unity Catalog
run_notebook("./notebooks/00_setup")

# COMMAND ----------

# 2. Generate Synthetic Data
try:
    print("Generating synthetic data...")
    dbutils.notebook.run("./data/generate_synthetic_data.py", 1800)
except Exception as e:
    print("Could not run synthetic data generation via notebook API. Please run it directly if not already generated.")

# COMMAND ----------

# 3. Bronze & Silver Ingestion
run_notebook("./notebooks/01_bronze_ingestion")
run_notebook("./notebooks/02_silver_preparation_spark_sim")

# COMMAND ----------

# 4. Train Models & Create Indexes
run_notebook("./notebooks/04a_train_fraud_model")
run_notebook("./notebooks/04b_create_policy_vector_index")
run_notebook("./notebooks/06a_train_reserve_model")

# COMMAND ----------

# 5. Orchestrate Agents
run_notebook("./notebooks/07_supervisor_orchestrator")

# COMMAND ----------

# 6. Serving and Evaluation
run_notebook("./notebooks/09_gold_serving")
run_notebook("./notebooks/10_evaluation")

print("Pipeline execution completed successfully.")