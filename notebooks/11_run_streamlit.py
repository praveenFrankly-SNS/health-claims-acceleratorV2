# Databricks notebook source
# MAGIC %md
# MAGIC # 11 Run Streamlit Dashboard
# MAGIC This notebook uses `dbtunnel` to host the Streamlit dashboard interactively inside your Databricks workspace.
# MAGIC Replaces 10_run_streamlit.py.
# MAGIC **Author:** SNS Square | **Version:** 1.0 | **Last Updated:** May 2026

# COMMAND ----------

# MAGIC %pip install dbtunnel[streamlit] streamlit pandas aiohttp

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import os
from dbtunnel import dbtunnel

notebook_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
app_path = os.path.abspath(os.path.join(notebook_dir, "..", "app", "app.py"))

print(f"Starting Streamlit app at: {app_path}")
dbtunnel.streamlit(app_path).run()