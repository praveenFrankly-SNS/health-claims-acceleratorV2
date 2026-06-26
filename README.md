# Health Claims Agentic Accelerator v2 (Serverless & Supabase-Ready)

This repository provides an end-to-end, multi-agent health claims processing accelerator designed for the Databricks platform. Version 2.0 introduces a robust relational database design, point-in-time correct feature engineering, and direct integration with an external database (such as Supabase PostgreSQL) for real-world deployment.

---

## 1. Process Architecture

```mermaid
graph TD
  local_gen[1. Local Synthetic Generator] -- Generates CSVs & Files --> local_csv[(Local Data Directory)]
  local_csv -- Populate Script --> supabase[(2. Supabase Cloud)]
  
  subgraph Databricks Workspace (Serverless Compute)
    setup[00_setup.py: Bootstrap Schemas & Volumes] --> bronze[01_bronze_ingestion.py: JDBC/Storage Sync]
    supabase -- JDBC & Storage API --> bronze
    bronze --> silver[02_silver_preparation_spark_sim.py: Feature Prep]
    silver --> train[04a/06a: Model Training & MLflow]
    train --> orchestrate[07_supervisor_orchestrator.py: LangGraph Orchestrator]
    orchestrate --> serving[09_gold_serving.py: Materialize Results]
    serving --> eval[10_evaluation.py: Pipeline Auditing]
  end

  orchestrate -.-> Agent1[Agent 1: Doc Intelligence]
  orchestrate -.-> Agent2[Agent 2: Fraud ML + LLM]
  orchestrate -.-> Agent3[Agent 3: Coverage RAG]
  orchestrate -.-> Agent4[Agent 4: Reserve Estimation]
  orchestrate -.-> Adjuster[Adjuster Allocation Override]
```

### Ingestion & Agent Workflows:
1. **Bootstrap & Schema DDLs (`00_setup`):** Configures tables with composite keys and Unity Catalog volumes on serverless compute.
2. **Bronze Ingestion (`01_bronze_ingestion`):** Pulls structured data via JDBC and downloads document proof attachments from **Supabase Storage** into Unity Catalog Volumes.
3. **Silver Feature Engineering (`02_silver_preparation_spark_sim`):** Materializes point-in-time correct aggregates strictly bounded by the claim's `date_of_loss`.
4. **Model Training (`04a_train_fraud_model`, `06a_train_reserve_model`):** Trains XGBoost classification and Quantile GBM models, registering them via MLflow.
5. **LangGraph Agent Orchestration (`07_supervisor_orchestrator`):**
   * **Agent 1 (Document Intelligence):** Direct metadata verification.
   * **Agent 2 (Fraud Detection):** Blends XGBoost score and LLM narrative checking.
   * **Agent 3 (Coverage RAG):** Evaluates exclusions using Vector Search.
   * **Agent 4 (Reserve Estimation):** Predicts reserving amounts and confidence bands.
   * **Adjuster Routing Override:** Automatically routes blacklisted provider claims directly to senior human field adjusters.

---

## 2. Setup & Deployment Workflow

Follow these steps sequentially to configure, seed, and run the pipeline.

### Step 1: Generate & Populate Data to Supabase (Local Environment)
Before deploying to Databricks, populate your external Supabase PostgreSQL instance and Storage buckets.

1. **Install Local Dependencies:**
   ```bash
   pip install supabase psycopg2-binary python-dotenv
   ```
2. **Configure Environment Variables:**
   Create a `.env` file in the project root:
   ```env
   SUPABASE_URL=https://<your-project-id>.supabase.co
   SUPABASE_SERVICE_KEY=<your-service-role-key>
   ```
3. **Generate Synthetic Data:**
   Generate the local mock records and files:
   ```bash
   python data/generate_synthetic_data.py --num-policies 80 --years 3 --claims-per-year 200
   ```
4. **Populate Supabase Database & Storage:**
   Upload the local tables and document attachments:
   ```bash
   python data/populate_supabase.py
   ```
   *Completion Criterion:* Verify that tables are populated in your Supabase SQL editor and the `policy-forms`, `discharge-summaries`, and `hospital-bills` buckets contain files in Supabase Storage.

---

### Step 2: Configure Workspace Secrets (Databricks Environment)
To run the notebooks without hardcoding credentials in git or job configurations, store your Supabase credentials securely inside the Databricks Secrets scope.

1. Open your Databricks Workspace and click on the `00_setup` notebook.
2. Create a temporary Python cell and execute the following API script to build the scope and secrets:
   ```python
   import requests
   ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
   api_url, api_token = ctx.apiUrl().get(), ctx.apiToken().get()
   headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}

   # 1. Create scope
   requests.post(f"{api_url.rstrip('/')}/api/2.0/secrets/scopes/create", headers=headers, json={"scope": "supabase", "initial_manage_principal": "users"})
   
   # 2. Put username and password (REPLACE with your database password)
   requests.post(f"{api_url.rstrip('/')}/api/2.0/secrets/put", headers=headers, json={"scope": "supabase", "key": "user", "string_value": "postgres.nerwqbauracfinfvunul"})
   requests.post(f"{api_url.rstrip('/')}/api/2.0/secrets/put", headers=headers, json={"scope": "supabase", "key": "password", "string_value": "YOUR_DATABASE_PASSWORD"})
   print("✓ Secrets successfully stored!")
   ```
3. **Delete the cell** after execution to ensure no credentials remain saved in the notebook file.

---

### Step 3: Deploy the Asset Bundle
Use Databricks Asset Bundles (DAB) to deploy and register the jobs.

1. **Configure Databricks CLI locally:**
   ```powershell
   databricks configure
   ```
2. **Deploy resources:**
   Deploy the bundle files and register the serverless compute workflow configurations:
   ```powershell
   databricks bundle deploy
   ```
   *Completion Criterion:* Ensure the terminal outputs `Deployment complete!` and the jobs are visible under the **Workflows > Jobs** tab in your Databricks sidebar.

---

### Step 4: Run the Pipelines (Databricks Environment)

#### 1. Setup & Model Training Pipeline (One-Time Execution)
* **Job:** `[MVP] Health Claims Setup and Training`
* **Trigger:** Click **Run Now** on the Workflows page.
* **Result:** Bootstraps catalog schemas, creates volumes, imports reference tables, trains the ML classifiers, and initializes the policy Vector index.

#### 2. Daily Processing Pipeline (Scheduled Run)
* **Job:** `[MVP] Health Claims Daily Inference`
* **Trigger:** Runs automatically daily at 2:00 AM UTC (or manual on-demand execution).
* **Result:** Automatically synchronizes new raw claims from Supabase, processes text proof attachments, runs the agentic evaluation, and materializes final reserve calculations.

---

## 3. Split-Application UI & Local Dev Workflow

The accelerator includes two professional, responsive dashboards designed to replace the legacy Streamlit code:
* **Customer Portal (Route `/customer`):** Allows policyholders to submit claims and upload documents (invoices, discharge summaries) directly into Supabase Storage.
* **Adjuster Workspace Portal (Routes `/`, `/review`, `/explorer`, `/analytics`):** Renders queue listings, interactive SVG LangGraph agent node flowchart logs, and Recharts business metrics.

### Local Development Setup:

To run and test the integrated React + FastAPI application locally:

1. **Install Frontend Dependencies:**
   ```bash
   cd app/frontend
   npm install
   ```

2. **Build and Serve Static React Bundle:**
   Compile the Vite frontend directly to the directory served by the backend:
   ```bash
   npm run build
   ```

3. **Start the Uvicorn Backend:**
   Run `databricks auth login` locally to authorize the Python SDK (U2M OAuth) without hardcoding credentials, then run:
   ```bash
   cd app
   uvicorn main:app --reload --port 8000
   ```
   Open `http://localhost:8000/` in your browser to access the combined interface.

4. **Guided Pitch Safeties:**
   To guarantee a zero-latency demo flow during customer pitches, use the **Guided Pitch** mode toggle on the main simulator. It triggers a client-side simulated trace for preset claims (e.g. low-risk auto-approved, high-risk fraud escalated, validation incomplete halt) that does not query the workspace SQL warehouse, protecting you against network delays and cold starts.

---

## 4. Local Verification & Testing

Verify that agent schemas, temporal parameters, and database rules are working correctly by executing the local test suite:

```bash
# Run the complete test suite locally
python -m pytest
```

### Implemented Test Invariants:
* **[test_point_in_time.py](file:///d:/Projects/AcceleratorBuilder/health-claims-acceleratorV2/tests/test_point_in_time.py):** Asserts that feature engineering does not leak future data.
* **[test_censoring_bias.py](file:///d:/Projects/AcceleratorBuilder/health-claims-acceleratorV2/tests/test_censoring_bias.py):** Verifies that `INVESTIGATION_PENDING` claims are excluded from the physician fraud denominator.
* **[test_floater_balance.py](file:///d:/Projects/AcceleratorBuilder/health-claims-acceleratorV2/tests/test_floater_balance.py):** Asserts that floater policies deplete a shared pool whereas individual policies track separate member balances.
* **[test_deterministic_coverage_math.py](file:///d:/Projects/AcceleratorBuilder/health-claims-acceleratorV2/tests/test_deterministic_coverage_math.py):** Asserts copays, room rent caps, waiting periods, and sub-limits without LLM calls.
* **[test_member_cross_validation.py](file:///d:/Projects/AcceleratorBuilder/health-claims-acceleratorV2/tests/test_member_cross_validation.py):** Asserts exact name-matching and blacklist adjuster routing overrides.
