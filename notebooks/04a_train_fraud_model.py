# Databricks notebook source
# MAGIC %md
# MAGIC # 04a Train Fraud Model
# MAGIC Trains an XGBoost model on the structured features from the Silver table to predict fraud.
# MAGIC Logs and registers the model in MLflow Unity Catalog.

# COMMAND ----------

# MAGIC %pip install xgboost scikit-learn pandas mlflow

# COMMAND ----------

try:
    dbutils.library.restartPython()
except Exception:
    pass

# COMMAND ----------

import os
import mlflow
import mlflow.xgboost
import pandas as pd
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

try:
    dbutils.widgets.text("catalog", "health_claims_dev")
    dbutils.widgets.text("schema", "claims")
    CATALOG_NAME = dbutils.widgets.get("catalog")
    SCHEMA_NAME = dbutils.widgets.get("schema")
except Exception:
    CATALOG_NAME = "health_claims_dev"
    SCHEMA_NAME = "claims"

MODEL_NAME = f"{CATALOG_NAME}.{SCHEMA_NAME}.fraud_detection_xgboost"

# Re-initialize Spark after restartPython() — the previous spark session is gone.
# SparkSession.getOrCreate() returns the existing active session on Databricks.
from pyspark.sql import SparkSession
spark = SparkSession.builder.getOrCreate()

# Load training data from silver_claims_history (the cumulative training table).
# CSV fallback is ONLY for running this notebook locally outside Databricks.
try:
    spark.sql(f"USE {CATALOG_NAME}.{SCHEMA_NAME}")
    history_table = f"{CATALOG_NAME}.{SCHEMA_NAME}.silver_claims_history"
    if spark.catalog.tableExists(history_table):
        df_silver = spark.table(history_table).toPandas()
        print(f"✓ Loaded {history_table}: {len(df_silver)} rows (cumulative training set)")
    else:
        print("WARNING: silver_claims_history not found — falling back to silver_claims.")
        print("Run 02_silver_preparation_spark_sim first to build the history table.")
        df_silver = spark.table(f"{CATALOG_NAME}.{SCHEMA_NAME}.silver_claims").toPandas()
        print(f"  Loaded silver_claims: {len(df_silver)} rows")
except Exception as e:
    print(f"Spark table load failed: {e}")
    print("Falling back to local CSV — training will use minimal data.")
    repo_root = "." if os.path.exists("./data") else ".."
    csv_path = f"{repo_root}/data/raw/training/claim_submissions_training.csv"
    if not os.path.exists(csv_path):
        csv_path = f"{repo_root}/data/raw/structured/claim_submissions.csv"
    df_silver = pd.read_csv(csv_path)
    df_silver['days_since_inception'] = df_silver.get('days_since_inception', 500)
    df_silver['amount_to_premium_ratio'] = df_silver.get('amount_to_premium_ratio',
        df_silver['claimed_amount'] / 10000)
    df_silver['claim_velocity'] = 0
    print(f"  Loaded CSV: {csv_path} ({len(df_silver)} rows)")

# COMMAND ----------

print(f"Training on {len(df_silver)} rows.")

# Features and target
features = ['claimed_amount', 'amount_to_premium_ratio', 'days_since_inception', 'claim_velocity']
target = 'is_fraud'

# Ensure columns exist
for f in features + [target]:
    if f not in df_silver.columns:
        df_silver[f] = 0

X = df_silver[features].fillna(0)
y = df_silver[target].fillna(0).astype(int)

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# COMMAND ----------

# MLflow run
mlflow.set_registry_uri("databricks-uc")

with mlflow.start_run(run_name="fraud_xgboost_training"):
    model = XGBClassifier(
        n_estimators=100, 
        max_depth=4, 
        learning_rate=0.1, 
        use_label_encoder=False, 
        eval_metric='logloss'
    )
    
    model.fit(X_train, y_train)
    
    # Evaluate
    y_pred = model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    prec = precision_score(y_test, y_pred, zero_division=0)
    rec = recall_score(y_test, y_pred, zero_division=0)
    f1 = f1_score(y_test, y_pred, zero_division=0)
    
    mlflow.log_metrics({
        "accuracy": acc,
        "precision": prec,
        "recall": rec,
        "f1": f1
    })
    
    print(f"Metrics: Accuracy={acc:.2f}, Precision={prec:.2f}, Recall={rec:.2f}")
    
    # Infer signature
    from mlflow.models.signature import infer_signature
    signature = infer_signature(X_train, model.predict(X_train))
    
    # Log model
    try:
        mlflow.xgboost.log_model(
            xgb_model=model,
            artifact_path="model",
            signature=signature,
            registered_model_name=MODEL_NAME
        )
        print(f"Model registered to Unity Catalog: {MODEL_NAME}")
    except Exception as e:
        print("Could not register to Unity Catalog (expected on Free Edition). Saving locally instead.")
        try:
            mlflow.xgboost.log_model(xgb_model=model, artifact_path="model", signature=signature)
        except Exception:
            pass

# Also save a local pickle for the orchestrator to use if MLflow is not configured locally
import pickle
os.makedirs("models", exist_ok=True)
with open("models/fraud_xgboost.pkl", "wb") as f:
    pickle.dump(model, f)
print("Saved local fallback model at models/fraud_xgboost.pkl")

# COMMAND ----------

print("Training Complete.")