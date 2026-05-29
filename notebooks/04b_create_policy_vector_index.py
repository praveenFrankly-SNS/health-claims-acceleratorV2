# Databricks notebook source
# MAGIC %md
# MAGIC # 04b Create Policy Vector Index
# MAGIC Parses policy form documents, saves chunks to a Delta table, and creates a Vector Search Index.
# MAGIC This replaces the local simulated RAG with a production-grade Databricks Vector Search endpoint.

# COMMAND ----------

# MAGIC %pip install databricks-vectorsearch

# COMMAND ----------

import IPython
try:
    dbutils.library.restartPython()
except Exception:
    pass

# COMMAND ----------

import os
import re
import time
from pyspark.sql import SparkSession
from pyspark.sql.types import StructType, StructField, StringType
from databricks.vector_search.client import VectorSearchClient

spark = SparkSession.builder.getOrCreate()

catalog_name = "health_claims_dev"
schema_name = "claims"
source_table = f"{catalog_name}.{schema_name}.policy_chunks"
vs_endpoint_name = "aml_policy_vs_endpoint"
vs_index_name = f"{catalog_name}.{schema_name}.policy_forms_index"
embedding_model = "databricks-bge-large-en"

# COMMAND ----------

# DBTITLE 1,Parse Policy Forms into Chunks
print("Parsing policy forms...")
repo_root = "." if os.path.exists("./data") else ".."
policy_dir = f"{repo_root}/data/policy_forms"

rows = []
# Ensure policy_dir exists
if os.path.exists(policy_dir):
    for filename in os.listdir(policy_dir):
        if filename.endswith(".txt"):
            plan_tier = filename.replace(".txt", "").capitalize()
            file_path = os.path.join(policy_dir, filename)
            
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                
                raw_sections = re.split(r'(Section \d+\.\d+)', content)
                if len(raw_sections) > 1:
                    for i in range(1, len(raw_sections), 2):
                        section_id = raw_sections[i].strip()
                        text = raw_sections[i+1].strip() if i+1 < len(raw_sections) else ""
                        if text:
                            # Create a unique chunk_id
                            chunk_id = f"{plan_tier}_{section_id}".replace(" ", "_")
                            # Combine section title and text for better embedding context
                            full_text = f"{section_id} - {text}"
                            rows.append((chunk_id, section_id, full_text, plan_tier))
else:
    print(f"Warning: Policy forms directory {policy_dir} not found. Skipping chunking.")

schema = StructType([
    StructField("chunk_id", StringType(), False),
    StructField("id", StringType(), True),
    StructField("text", StringType(), True),
    StructField("plan_tier", StringType(), True)
])

df = spark.createDataFrame(rows, schema)
print(f"Parsed {df.count()} total sections across all policy forms.")

# COMMAND ----------

# DBTITLE 1,Write to Delta Table and Enable CDF
print(f"Writing chunks to {source_table}...")

df.write.format("delta").mode("overwrite").saveAsTable(source_table)

spark.sql(f"""
  ALTER TABLE {source_table}
  SET TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
""")
print("CDF enabled on source table.")

# COMMAND ----------

# DBTITLE 1,Create Vector Search Endpoint
vsc = VectorSearchClient(disable_notice=True)

def wait_for_endpoint(client, endpoint_name, timeout_minutes=20):
    deadline = time.time() + timeout_minutes * 60
    while time.time() < deadline:
        try:
            ep = client.get_endpoint(endpoint_name)
            state = ep.get("endpoint_status", {}).get("state", "UNKNOWN")
            print(f"Endpoint state: {state}")
            if state == "ONLINE":
                return True
        except Exception as e:
            if "does not exist" not in str(e).lower():
                raise
        time.sleep(30)
    raise TimeoutError("Endpoint creation timed out")

print(f"Checking for endpoint: {vs_endpoint_name}")
try:
    ep = vsc.get_endpoint(vs_endpoint_name)
    print("Endpoint exists.")
    wait_for_endpoint(vsc, vs_endpoint_name)
except Exception as e:
    if "does not exist" in str(e).lower() or "not found" in str(e).lower():
        print(f"Creating endpoint: {vs_endpoint_name}...")
        vsc.create_endpoint(name=vs_endpoint_name, endpoint_type="STANDARD")
        wait_for_endpoint(vsc, vs_endpoint_name)
    else:
        raise

# COMMAND ----------

# DBTITLE 1,Create Delta Sync Index
def wait_for_index(client, endpoint_name, index_name, timeout_minutes=30):
    deadline = time.time() + timeout_minutes * 60
    while time.time() < deadline:
        try:
            idx = client.get_index(endpoint_name, index_name)
            state = idx.describe().get("status", {}).get("ready", False)
            message = idx.describe().get("status", {}).get("message", "")
            print(f"Index ready: {state} | {message[:80]}")
            if state:
                return True
        except Exception as e:
            pass
        time.sleep(30)
    raise TimeoutError("Index creation timed out")

print(f"Checking for index: {vs_index_name}")
try:
    idx = vsc.get_index(vs_endpoint_name, vs_index_name)
    print("Index exists. Triggering sync...")
    idx.sync()
    wait_for_index(vsc, vs_endpoint_name, vs_index_name)
except Exception as e:
    if "does not exist" in str(e).lower() or "not found" in str(e).lower():
        print(f"Creating Delta Sync Index: {vs_index_name}...")
        vsc.create_delta_sync_index(
            endpoint_name=vs_endpoint_name,
            index_name=vs_index_name,
            source_table_name=source_table,
            pipeline_type="TRIGGERED",
            primary_key="chunk_id",
            embedding_source_column="text",
            embedding_model_endpoint_name=embedding_model
        )
        print("Waiting for initial sync (this can take 5-10 minutes)...")
        wait_for_index(vsc, vs_endpoint_name, vs_index_name)
    else:
        raise

print("✅ Vector Search Pipeline Complete! Agent 3 can now use the real Databricks Vector Search.")