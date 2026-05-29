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

CATALOG_NAME = "health_claims_dev"
SCHEMA_NAME = "claims"
MODEL_NAME = f"{CATALOG_NAME}.{SCHEMA_NAME}.fraud_detection_xgboost"

# Try to use Spark to get the data if in Databricks, otherwise fallback to local CSVs
try:
    spark.sql(f"USE {CATALOG_NAME}.{SCHEMA_NAME}")
    df_silver = spark.table("silver_claims").toPandas()
except Exception as e:
    print(f"Running locally without Databricks Spark context: {e}")
    # Fallback for local testing if needed
    repo_root = "." if os.path.exists("./data") else ".."
    df_silver = pd.read_csv(f"{repo_root}/data/raw/structured/claims.csv")
    # Stub missing features for local run
    df_silver['days_since_inception'] = 500
    df_silver['amount_to_premium_ratio'] = df_silver['claimed_amount'] / 10000
    df_silver['claim_velocity'] = 0

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