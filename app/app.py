import streamlit as st

# MUST be the first Streamlit command
st.set_page_config(page_title="Health Claims AI", layout="wide", initial_sidebar_state="expanded")

import pandas as pd
import json
import time
import os
import sys

# Ensure src module is in path
app_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(app_dir, ".."))
if repo_root not in sys.path:
    sys.path.append(repo_root)

# Try to import databricks.connect for Serverless compute
try:
    from databricks.connect import DatabricksSession
    cluster_id = os.environ.get("DATABRICKS_CLUSTER_ID")
    builder = DatabricksSession.builder
    if cluster_id:
        builder = builder.clusterId(cluster_id)
    else:
        builder = builder.serverless()
    spark = builder.getOrCreate()
except Exception as e:
    st.error("Could not initialize DatabricksSession. Are you running outside Databricks?")
    spark = None

catalog = "health_claims_dev"
schema = "claims"
audit_schema = "audit"

st.title("🏥 Health Claims AI Adjuster")

# -------------------------------------------------------------
# Database Helpers
# -------------------------------------------------------------
def get_pending_claims():
    if not spark:
        return pd.DataFrame()
    try:
        # Get recent claims to simulate
        df = spark.sql(f"""
            SELECT * FROM {catalog}.{schema}.silver_claims 
            ORDER BY claim_id ASC LIMIT 50
        """).toPandas()
        if df.empty:
            df = spark.sql(f"SELECT * FROM {catalog}.{schema}.silver_claims LIMIT 5").toPandas()
        return df
    except Exception as e:
        st.error(f"Error reading silver claims: {e}")
        return pd.DataFrame()

def record_decision(claim_id, decision, reason=""):
    if spark:
        try:
            spark.sql(
                f"INSERT INTO {catalog}.{audit_schema}.adjuster_decisions (claim_id, action, reason, user, timestamp) VALUES (?, ?, ?, 'Adjuster', current_timestamp())",
                args=[claim_id, decision, reason]
            )
            return True
        except Exception as e:
            st.error(f"Error recording decision: {e}")
            return False
    return False

# -------------------------------------------------------------
# Tabs
# -------------------------------------------------------------
tab1, tab2, tab3, tab4 = st.tabs([
    "🔴 Live Simulator", 
    "👨‍⚖️ Adjuster Review", 
    "🥇 Gold Explorer",
    "📈 Analytics"
])

with tab1:
    st.header("Live Claim Adjudication Simulator")
    
    df_claims = get_pending_claims()
    if not df_claims.empty:
        claim_options = {f"{row['claim_id']}": row for _, row in df_claims.iterrows()}
        selected_claim_id = st.selectbox("Select an incoming Silver Claim:", list(claim_options.keys()))
        
        if st.button("Trigger AI Adjudication", type="primary"):
            selected_claim = claim_options[selected_claim_id]
            inv_id = selected_claim['claim_id']
            
            # Show raw source document outside the status block to prevent nesting errors
            file_path = f"{repo_root}/data/raw/unstructured/{inv_id}_discharge_summary.txt"
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    raw_text = f.read()
                with st.expander(f"📄 View Source Discharge Summary ({inv_id})", expanded=False):
                    st.text(raw_text)
            
            with st.status(f"Processing Claim {inv_id}...", expanded=True) as status:
                if not spark:
                    st.error("Databricks Session not found. Cannot run agents locally without Databricks Connect.")
                    status.update(label="Investigation Failed", state="error", expanded=True)
                else:
                    st.write("Initializing Agents...")
                    from src.agents.doc_intelligence import agent1_doc_intelligence
                    from src.agents.fraud import agent2_fraud
                    from src.agents.coverage import agent3_coverage
                    from src.agents.reserve import agent4_reserve
                    from src.agents.adjuster_allocation import allocate_adjuster
                    
                    claim_state = {
                        "claim_id": inv_id,
                        "days_since_inception": selected_claim.get("days_since_inception", 500),
                        "claim_velocity": selected_claim.get("claim_velocity", 0),
                        "amount_to_premium_ratio": float(selected_claim.get("amount_to_premium_ratio", 0)),
                        "pipeline_status": "RUNNING"
                    }
                    
                    # Agent 1
                    st.write("📄 Agent 1: Document Intelligence Extracting Fields...")
                            
                    try:
                        claim_state = agent1_doc_intelligence(claim_state, spark=spark)
                        st.json(claim_state.get('extracted_data', {}))
                        st.markdown(f"- **Completeness Score:** `{claim_state.get('completeness_score')}` | **Cross-Validation:** `{claim_state.get('cross_validation_status')}`")
                    except Exception as e:
                        st.error(f"Agent 1 Failed: {e}")
                        
                    if claim_state.get('cross_validation_status') != "PASSED":
                        st.warning("Claim halted due to validation failure.")
                        if 'cross_validation_error' in claim_state.get('extracted_data', {}):
                            st.error(f"Cross-Validation Exception: {claim_state['extracted_data']['cross_validation_error']}")
                        claim_state["pipeline_status"] = "HALTED_INCOMPLETE"
                    else:
                        # Agent 2
                        st.write("🕵️ Agent 2: Fraud Detection Scoring...")
                        try:
                            claim_state = agent2_fraud(claim_state, spark=spark)
                            st.json(claim_state.get('fraud', {}))
                        except Exception as e:
                            st.error(f"Agent 2 Failed: {e}")
                            
                        # Agent 3
                        st.write("🛡️ Agent 3: Coverage Analysis via RAG...")
                        try:
                            claim_state = agent3_coverage(claim_state)
                            st.json(claim_state.get('coverage', {}))
                        except Exception as e:
                            st.error(f"Agent 3 Failed: {e}")
                            
                        # Agent 4
                        st.write("💰 Agent 4: Reserve Prediction...")
                        try:
                            claim_state = agent4_reserve(claim_state, spark=spark)
                            st.json(claim_state.get('reserve', {}))
                        except Exception as e:
                            st.error(f"Agent 4 Failed: {e}")
                            
                        # Agent 5
                        st.write("⚖️ Supervisor: Allocating Adjuster...")
                        try:
                            claim_state = allocate_adjuster(claim_state)
                            st.success(f"Assigned to: **{claim_state.get('adjuster_allocation')}**")
                        except Exception as e:
                            st.error(f"Allocation Failed: {e}")
                            
                        claim_state["pipeline_status"] = "COMPLETED"

                    st.write("💾 Writing Decision to Gold Table...")
                    try:
                        from pyspark.sql import Row
                        df_gold_new = spark.createDataFrame([Row(claim_id=inv_id, payload=json.dumps(claim_state))])
                        gold_full_name = f"{catalog}.{schema}.gold_claim_decisions"
                        df_gold_new.createOrReplaceTempView("tmp_gold")
                        spark.sql(f"""
                            MERGE INTO {gold_full_name} t
                            USING tmp_gold s
                            ON t.claim_id = s.claim_id
                            WHEN MATCHED THEN UPDATE SET *
                            WHEN NOT MATCHED THEN INSERT *
                        """)
                        st.markdown("- `[DONE]` Saved to Delta Lake.")
                    except Exception as e:
                        st.error(f"Failed to write to Gold Table: {e}")
                    
                    status.update(label="AI Adjudication Complete", state="complete", expanded=False)
                    st.success("Investigation complete! Please review the results in the Adjuster Review tab.")
    else:
        st.info("No pending claims to simulate.")

with tab2:
    st.header("Human-in-the-Loop: Claims Queue")
    
    if spark:
        try:
            df_dash = spark.sql(f"SELECT * FROM {catalog}.{schema}.vw_claims_dashboard").toPandas()
            st.dataframe(df_dash, use_container_width=True)
            
            if not df_dash.empty:
                st.subheader("Action Claim")
                action_options = {f"{row['claim_id']}": row for _, row in df_dash.iterrows()}
                selected_action_id = st.selectbox("Select Claim to Action:", list(action_options.keys()))
                
                col1, col2, col3 = st.columns(3)
                if col1.button("✅ Approve Claim", type="primary", use_container_width=True):
                    if record_decision(selected_action_id, "APPROVED", "Approved by manual review"):
                        st.success(f"Claim {selected_action_id} Approved.")
                if col2.button("❌ Deny Claim", use_container_width=True):
                    if record_decision(selected_action_id, "DENIED", "Denied by manual review"):
                        st.warning(f"Claim {selected_action_id} Denied.")
                if col3.button("🔍 Request Investigation", use_container_width=True):
                    if record_decision(selected_action_id, "INVESTIGATE", "Sent to SIU"):
                        st.info(f"Claim {selected_action_id} escalated for Investigation.")
            
            st.subheader("Audit Trail")
            try:
                df_audit = spark.sql(f"SELECT * FROM {catalog}.{audit_schema}.adjuster_decisions ORDER BY timestamp DESC LIMIT 20").toPandas()
                st.dataframe(df_audit, use_container_width=True)
            except Exception as e:
                st.warning("Audit table not found or empty.")
            
        except Exception as e:
            st.error(f"Error loading dashboard: {e}")
    else:
        st.write("No database connection active.")

with tab3:
    st.header("Gold Data Explorer")
    if spark:
        try:
            df_gold_raw = spark.sql(f"SELECT claim_id, payload FROM {catalog}.{schema}.gold_claim_decisions ORDER BY claim_id DESC").toPandas()
            
            if not df_gold_raw.empty:
                # Parse JSON to create a better display table
                display_data = []
                for _, row in df_gold_raw.iterrows():
                    cid = row['claim_id']
                    try:
                        p = json.loads(row['payload'])
                        display_data.append({
                            "Claim ID": cid,
                            "Pipeline Status": p.get("pipeline_status", "UNKNOWN"),
                            "Coverage": p.get("coverage", {}).get("coverage_status", "UNKNOWN"),
                            "Fraud Score": p.get("fraud", {}).get("fraud_score", "N/A"),
                            "Adjuster": p.get("adjuster_allocation", "N/A")
                        })
                    except:
                        display_data.append({"Claim ID": cid, "Pipeline Status": "ERROR PARSING JSON"})
                        
                df_display = pd.DataFrame(display_data)
                st.dataframe(df_display, use_container_width=True)
                
                st.subheader("View Full JSON Payload")
                selected_gold_id = st.selectbox("Select a claim to view its full JSON payload:", df_gold_raw['claim_id'].tolist())
                if selected_gold_id:
                    payload_row = spark.sql(f"SELECT payload FROM {catalog}.{schema}.gold_claim_decisions WHERE claim_id = '{selected_gold_id}'").toPandas()
                    if not payload_row.empty:
                        payload_str = payload_row['payload'].values[0]
                        try:
                            st.json(json.loads(payload_str))
                        except Exception:
                            st.text(payload_str)
        except Exception as e:
            st.error(f"Could not load Gold table: {e}")
    else:
        st.write("No database connection active.")

with tab4:
    st.header("Claims Adjudication Analytics")
    
    total_claims = 0
    auto_approved = 0
    total_reserve = 0.0
    
    if spark:
        try:
            df_dash = spark.sql(f"SELECT * FROM {catalog}.{schema}.vw_claims_dashboard").toPandas()
            total_claims = len(df_dash)
            auto_approved = len(df_dash[df_dash['assigned_adjuster'] == 'AUTO_APPROVED'])
            total_reserve = df_dash['reserve_amount'].astype(float).sum()
        except:
            pass
            
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Processed Claims", str(total_claims))
    c2.metric("Avg. AI Processing Time", "4.2 sec", "-1.1s")
    if total_claims > 0:
        c3.metric("Auto-Adjudication Rate", f"{(auto_approved/total_claims)*100:.1f}%")
    else:
        c3.metric("Auto-Adjudication Rate", "0.0%")
    c4.metric("Total Initial Reserve", f"${total_reserve:,.2f}")
