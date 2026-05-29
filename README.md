# Health Claims Agentic Accelerator

This repository provides an end-to-end, agentic claims processing accelerator built for the Databricks platform. It leverages LLMs and ML models to automate document extraction, fraud detection, coverage eligibility (RAG), reserve estimation, and adjuster routing.

## Overview of the Pipeline

1. **Bronze & Silver Data Pipelines**: Ingests raw structured CSVs and unstructured TXT discharge summaries into Delta tables. Cleans and hashes PII.
2. **Agent 1 (Document Intelligence)**: Extracts structured data from clinical text and cross-validates against the policy master table.
3. **Agent 2 (Fraud ML + LLM)**: Uses an XGBoost model on historical data plus an LLM reasoning engine to flag anomalous claims.
4. **Agent 3 (Coverage RAG)**: Determines policy coverage using semantic search (Sentence Transformers) over tier-specific policy form documents, protected by a hallucination guard.
5. **Agent 4 (Reserve Estimation)**: Combines Quantile GBM predictions with LLM-based medical severity uplift to recommend a financial reserve and confidence interval.
6. **Supervisor Orchestrator**: Uses LangGraph to orchestrate the multi-agent workflow sequentially and handles deterministic adjuster allocation based on YAML thresholds.

## Free Edition Limitations & Paid Upgrade Path

This accelerator is designed to run on Databricks Free Edition with the following constraints:
- **Sequential Orchestration**: LangGraph executes sequentially (Agent 1 → 2 → 3 → 4) rather than parallel due to Free Edition concurrent task limits. 
- **Simulated Vector Search**: Agent 3 uses a local `sentence-transformers` model to simulate semantic similarity instead of a persistent Databricks Vector Search index.
- **Local Fallbacks**: Models are saved via `pickle` locally as a fallback, although MLflow logging is fully implemented.

### 🚀 Upgrading to a Paid Workspace
To unlock the full production capabilities of this accelerator, you should upgrade to a paid Databricks workspace. This enables:
1. **Databricks Vector Search**: Replace the local sentence-transformers in Agent 3 with a fully managed, auto-updating Vector Search Index over Unity Catalog Volumes.
2. **Agent Bricks Supervisor**: Upgrade the LangGraph orchestrator to use Databricks Agent Framework (Agent Bricks), enabling true parallel agent execution, advanced state management, and built-in MLflow Tracing.
3. **Model Serving Endpoints**: Host the Fraud (XGBoost) and Reserve (GBM) models on dedicated serverless REST endpoints instead of batch loading them in the notebooks.
4. **dbtunnel UI**: Host the Streamlit dashboard persistently 24/7.

## Getting Started

1. Set your `DATABRICKS_HOST` and `DATABRICKS_TOKEN` environment variables (or rely on notebook context).
2. Run `data/generate_synthetic_data.py` to generate the mock dataset.
3. Execute notebooks `00` through `02` to set up the Medallion architecture.
4. Run the training scripts `04a_train_fraud_model.py` and `06a_train_reserve_model.py`.
5. Execute `07_supervisor_orchestrator.py` to process claims end-to-end!
6. Run `10_evaluation.py` to test accuracy against the ground truth.
