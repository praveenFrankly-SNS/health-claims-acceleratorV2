# Databricks notebook source
# MAGIC %md
# MAGIC # 07 Supervisor Orchestrator
# MAGIC Uses LangGraph to orchestrate the 4 agents.
# MAGIC Agents 2 and 3 run sequentially.

# COMMAND ----------

# MAGIC %pip install langgraph langchain-core sentence-transformers xgboost mlflow

# COMMAND ----------

# Automatically restart Python to ensure typing_extensions updates are loaded cleanly
try:
    dbutils.library.restartPython()
except Exception:
    pass

# COMMAND ----------

import os
import sys
import json
import yaml
import mlflow
from pyspark.sql import SparkSession
from langgraph.graph import StateGraph, END
from typing import TypedDict, Dict, Any

dbutils.widgets.text("catalog", "health_claims_dev")
dbutils.widgets.text("schema", "claims")
CATALOG_NAME = dbutils.widgets.get("catalog")
SCHEMA_NAME = dbutils.widgets.get("schema")

# Ensure we can import the agent functions from src package
notebook_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
repo_root = os.path.abspath(os.path.join(notebook_dir, ".."))
sys.path.append(repo_root)

from src.agents.doc_intelligence import agent1_doc_intelligence
from src.agents.fraud import agent2_fraud
from src.agents.coverage import agent3_coverage
from src.agents.reserve import agent4_reserve
from src.agents.adjuster_allocation import allocate_adjuster

# Load thresholds
with open(f"{repo_root}/config/thresholds.yml", "r") as f:
    thresholds = yaml.safe_load(f)

# COMMAND ----------

# LangGraph State definition
class ClaimState(TypedDict):
    claim_id: str
    extracted_data: dict
    completeness_score: float
    missing_fields: list
    cross_validation_status: str
    fraud: dict
    coverage: dict
    reserve: dict
    adjuster_allocation: str
    pipeline_status: str
    
def safe_agent_call(agent_func, state):
    if state.get("pipeline_status") == "AGENT_ERROR":
        return state
    try:
        return agent_func(state)
    except Exception as e:
        print(f"[Orchestrator] Agent Error: {e}")
        state["pipeline_status"] = "AGENT_ERROR"
        return state

# Node wrappers
def node_agent1(state: ClaimState):
    print(f"\n[Orchestrator] Running Agent 1 for {state['claim_id']}")
    return safe_agent_call(agent1_doc_intelligence, dict(state))

def node_agent2(state: ClaimState):
    print(f"\n[Orchestrator] Running Agent 2 for {state['claim_id']}")
    return safe_agent_call(agent2_fraud, dict(state))

def node_agent3(state: ClaimState):
    print(f"\n[Orchestrator] Running Agent 3 for {state['claim_id']}")
    return safe_agent_call(agent3_coverage, dict(state))

def node_agent4(state: ClaimState):
    print(f"\n[Orchestrator] Running Agent 4 for {state['claim_id']}")
    return safe_agent_call(agent4_reserve, dict(state))

def node_allocate(state: ClaimState):
    print(f"\n[Orchestrator] Running Allocation for {state['claim_id']}")
    return safe_agent_call(allocate_adjuster, dict(state))

def node_halt(state: ClaimState):
    print(f"\n[Orchestrator] Halting pipeline for {state['claim_id']}")
    return {"pipeline_status": "HALTED_INCOMPLETE"}

def node_post_doc_check(state: ClaimState):
    if state.get("pipeline_status") == "AGENT_ERROR":
        return state
    print(f"\n[Orchestrator] Post-Doc Check passed for {state['claim_id']}. Proceeding to subsequent agents.")
    return state

# COMMAND ----------

# Define the Graph
workflow = StateGraph(ClaimState)

workflow.add_node("agent1", node_agent1)
workflow.add_node("post_doc_check", node_post_doc_check)
workflow.add_node("agent2", node_agent2)
workflow.add_node("agent3", node_agent3)
workflow.add_node("agent4", node_agent4)
workflow.add_node("allocate", node_allocate)
workflow.add_node("halt", node_halt)

# Conditional edge after Agent 1
def should_continue(state: ClaimState) -> str:
    if state.get("pipeline_status") == "AGENT_ERROR":
        return "halt"
    min_score = thresholds.get("completeness_score_min", 0.80)
    if state.get("completeness_score", 0) < min_score or state.get("cross_validation_status") != "PASSED":
        return "halt"
    return "continue"

workflow.set_entry_point("agent1")

# Add conditional edges from agent1
workflow.add_conditional_edges(
    "agent1",
    should_continue,
    {
        "halt": "halt",
        "continue": "post_doc_check" 
    }
)

# Sequential flow for the remaining agents
workflow.add_edge("post_doc_check", "agent2")
workflow.add_edge("agent2", "agent3")
workflow.add_edge("agent3", "agent4")

workflow.add_edge("agent4", "allocate")
workflow.add_edge("allocate", END)
workflow.add_edge("halt", END)

app = workflow.compile()

# COMMAND ----------

spark = SparkSession.builder.getOrCreate()
spark.sql(f"USE {CATALOG_NAME}.{SCHEMA_NAME}")

silver_table = "silver_claims"
gold_table = "gold_claim_decisions"

try:
    df_silver = spark.table(silver_table)
    
    if spark.catalog.tableExists(f"{CATALOG_NAME}.{SCHEMA_NAME}.{gold_table}"):
        df_gold = spark.table(gold_table).select("claim_id")
        df_new_claims = df_silver.join(df_gold, on="claim_id", how="left_anti")
    else:
        df_new_claims = df_silver
        
    claims_to_process = [row.asDict() for row in df_new_claims.collect()]
except Exception as e:
    print(f"Could not read silver table: {e}. Using dummy IDs.")
    claims_to_process = [{"claim_id": "CLM-2026-10000"}]

results = []
# Set an MLflow experiment for the orchestrator run
try:
    mlflow.set_experiment(f"/Shared/{CATALOG_NAME}_{SCHEMA_NAME}_orchestrator")
except:
    pass

for claim in claims_to_process:
    claim_id = claim.get("claim_id")
    initial_state = {
        "claim_id": claim_id,
        "days_since_inception": claim.get("days_since_inception", 500),
        "claim_velocity": claim.get("claim_velocity", 0),
        "amount_to_premium_ratio": claim.get("amount_to_premium_ratio", 0),
        "pipeline_status": "RUNNING"
    }
    
    with mlflow.start_run(run_name=f"Claim_{claim_id}", nested=True):
        mlflow.log_param("claim_id", claim_id)
        
        final_state = app.invoke(initial_state)
        
        if final_state.get("pipeline_status") == "RUNNING":
            final_state["pipeline_status"] = "COMPLETED"
            
        mlflow.log_param("pipeline_status", final_state.get("pipeline_status"))
        results.append(final_state)

# Write to Gold Table
if results:
    from pyspark.sql import Row
    rows = [Row(claim_id=r.get("claim_id", "UNKNOWN"), payload=json.dumps(r)) for r in results]
    df_gold_new = spark.createDataFrame(rows)
    
    gold_full_name = f"{CATALOG_NAME}.{SCHEMA_NAME}.{gold_table}"
    print(f"Writing {len(rows)} Gold decision packets to {gold_full_name} via MERGE...")
    
    if spark.catalog.tableExists(gold_full_name):
        from delta.tables import DeltaTable
        deltaTable = DeltaTable.forName(spark, gold_full_name)
        deltaTable.alias("t").merge(
            df_gold_new.alias("s"),
            "t.claim_id = s.claim_id"
        ).whenMatchedUpdateAll().whenNotMatchedInsertAll().execute()
    else:
        df_gold_new.write.format("delta").saveAsTable(gold_full_name)
        spark.sql(f"ALTER TABLE {gold_full_name} SET TBLPROPERTIES ('sensitivity'='PHI', 'classification'='restricted')")
else:
    print("No new claims to process.")

print("Orchestration complete.")