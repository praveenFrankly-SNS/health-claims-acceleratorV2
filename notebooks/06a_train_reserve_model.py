# Databricks notebook source
# MAGIC %md
# MAGIC # 06a Train Reserve Model
# MAGIC Trains a Gradient Boosting Regressor on historical settlements.
# MAGIC Logs and registers the model in MLflow Unity Catalog.

# COMMAND ----------

# MAGIC %pip install scikit-learn pandas mlflow

# COMMAND ----------

try:
    dbutils.library.restartPython()
except Exception:
    pass

# COMMAND ----------

import os
import mlflow
import mlflow.sklearn
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.pipeline import Pipeline
import pickle

try:
    dbutils.widgets.text("catalog", "health_claims_dev")
    dbutils.widgets.text("schema", "claims")
    CATALOG_NAME = dbutils.widgets.get("catalog")
    SCHEMA_NAME = dbutils.widgets.get("schema")
except Exception:
    CATALOG_NAME = "health_claims_dev"
    SCHEMA_NAME = "claims"
MODEL_NAME = f"{CATALOG_NAME}.{SCHEMA_NAME}.reserve_estimation_gbm"

# Re-initialize Spark after restartPython()
from pyspark.sql import SparkSession
spark = SparkSession.builder.getOrCreate()

try:
    spark.sql(f"USE {CATALOG_NAME}.{SCHEMA_NAME}")
    df_history = spark.table(f"{CATALOG_NAME}.{SCHEMA_NAME}.claims_history").toPandas()
    print(f"✓ Loaded claims_history: {len(df_history)} rows")
except Exception as e:
    print(f"Spark table load failed: {e}")
    print("Falling back to local CSV")
    repo_root = "." if os.path.exists("./data") else ".."
    df_history = pd.read_csv(f"{repo_root}/data/raw/structured/claims_history.csv")

# COMMAND ----------

print(f"Training Reserve Model on {len(df_history)} historical claims.")

# For a simple regression, we predict 'settled_amount' using 'diagnosis_icd'
# (In a real scenario, we'd use hospital tier, plan tier, age, etc.)

features = ['diagnosis_icd']
target = 'settled_amount'

# Drop missing values
df_history = df_history.dropna(subset=[target])

X = df_history[features]
y = df_history[target]

# We will train a pipeline that handles categorical encoding
preprocessor = ColumnTransformer(
    transformers=[
        ('cat', OneHotEncoder(handle_unknown='ignore'), ['diagnosis_icd'])
    ])

# Train 3 models for P10, P50, P90
model_p50 = Pipeline(steps=[
    ('preprocessor', preprocessor),
    ('regressor', GradientBoostingRegressor(loss='quantile', alpha=0.5, n_estimators=50, random_state=42))
])
model_p10 = Pipeline(steps=[
    ('preprocessor', preprocessor),
    ('regressor', GradientBoostingRegressor(loss='quantile', alpha=0.1, n_estimators=50, random_state=42))
])
model_p90 = Pipeline(steps=[
    ('preprocessor', preprocessor),
    ('regressor', GradientBoostingRegressor(loss='quantile', alpha=0.9, n_estimators=50, random_state=42))
])

# Fit models
model_p50.fit(X, y)
model_p10.fit(X, y)
model_p90.fit(X, y)

# COMMAND ----------

# MLflow run
mlflow.set_registry_uri("databricks-uc")

# We will just log the P50 model to MLflow for simplicity, 
# or a custom python model wrapping all 3.
# For this accelerator, we'll log P50 as the primary MLflow model, 
# and save a local dictionary containing all 3 for the agent to load.

with mlflow.start_run(run_name="reserve_gbm_training"):
    
    # Evaluate P50 on train set for basic metrics
    from sklearn.metrics import mean_absolute_error
    y_pred_p50 = model_p50.predict(X)
    mae = mean_absolute_error(y, y_pred_p50)
    
    mlflow.log_metric("train_mae", mae)
    print(f"P50 Model Training MAE: {mae:.2f}")
    
    # Infer signature
    from mlflow.models.signature import infer_signature
    signature = infer_signature(X, model_p50.predict(X))
    
    try:
        mlflow.sklearn.log_model(
            sk_model=model_p50,
            artifact_path="model_p50",
            signature=signature,
            registered_model_name=MODEL_NAME
        )
        print(f"P50 Model registered to Unity Catalog: {MODEL_NAME}")
    except Exception as e:
        print("Could not register to Unity Catalog (expected on Free Edition). Saving locally instead.")
        try:
            mlflow.sklearn.log_model(sk_model=model_p50, artifact_path="model_p50", signature=signature)
        except Exception:
            pass

# Save all 3 to a local pickle file to simulate a multi-model artifact
os.makedirs("models", exist_ok=True)
models_dict = {
    "P10": model_p10,
    "P50": model_p50,
    "P90": model_p90
}
with open("models/reserve_gbms.pkl", "wb") as f:
    pickle.dump(models_dict, f)
    
print("Saved local fallback models at models/reserve_gbms.pkl")