from pyspark.sql import SparkSession

print("Attempting to initialize SparkSession with master('local[*]')...")
try:
    spark = SparkSession.builder.master("local[*]").getOrCreate()
    print("SUCCESS: Local SparkSession initialized successfully!")
    print(f"Spark version: {spark.version}")
    spark.stop()
except Exception as e:
    print(f"ERROR: Failed to initialize local SparkSession: {e}")
