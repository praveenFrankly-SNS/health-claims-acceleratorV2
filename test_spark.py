import os
import sys
from dotenv import load_dotenv

# Ensure repository root is in python path
app_dir = r"c:\Users\ADMIN\Projects\Databricks\Accelerators\DatabricksAccelerator\Health-claims-accelerator\health-claims-acceleratorV2\app"
repo_root = os.path.abspath(os.path.join(app_dir, ".."))
sys.path.append(repo_root)

# Load environment variables
load_dotenv(os.path.join(repo_root, ".env"))

print("Attempting to initialize Databricks Connect...")
try:
    from databricks.connect import DatabricksSession
    cluster_id = os.environ.get("DATABRICKS_CLUSTER_ID")
    builder = DatabricksSession.builder
    if cluster_id:
        builder = builder.clusterId(cluster_id)
    else:
        builder = builder.serverless()
    spark = builder.getOrCreate()
    print("SUCCESS: Initialized DatabricksSession!")
except Exception as e:
    print(f"ERROR: Databricks Connect could not initialize: {e}")
    print("\nAttempting to initialize local SparkSession fallback...")
    try:
        from pyspark.sql import SparkSession
        spark = SparkSession.builder.getOrCreate()
        print("SUCCESS: Initialized local SparkSession fallback!")
    except Exception as local_e:
        print(f"ERROR: Local Spark Session initialization failed: {local_e}")
