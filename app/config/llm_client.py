import os
import json
import urllib.request
import urllib.error
from typing import Optional, List
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Pydantic Models — typed contracts at agent seams
# ---------------------------------------------------------------------------

class DocExtractionOutput(BaseModel):
    """Output from Agent 1 (Document Intelligence) LLM extraction."""
    policy_number: Optional[str] = None
    claimant_name: Optional[str] = None
    admission_date: Optional[str] = None
    discharge_date: Optional[str] = None
    hospital_name: Optional[str] = None
    diagnosis_icd: Optional[str] = None
    claimed_amount: Optional[int] = None
    attending_physician_registration_number: Optional[str] = None


class MemberValidation(BaseModel):
    """Result of cross-validating extracted data against policy_members."""
    status: str = Field(description="PASSED, FAILED_POLICY_NOT_FOUND, FAILED_POLICY_LAPSED, "
                                    "FAILED_NAME_MISMATCH, FAILED_COVERAGE_PERIOD, SKIPPED_DUE_TO_ERROR")
    matched_member_id: Optional[str] = None
    matched_member_name: Optional[str] = None
    relationship_to_primary: Optional[str] = None
    coverage_start_date: Optional[str] = None
    coverage_end_date: Optional[str] = None
    error_detail: Optional[str] = None


class FraudLLMOutput(BaseModel):
    """Output from Agent 2 (Fraud) LLM narrative analysis."""
    llm_fraud_score: float = 0.1
    narrative_signals: List[str] = Field(default_factory=list)
    reasoning: str = "Normal claim processing."


class FraudResult(BaseModel):
    """Combined fraud assessment (ML + LLM blend)."""
    fraud_score: float
    confidence: str = Field(description="HIGH, MEDIUM, LOW")
    fraud_signals: List[str] = Field(default_factory=list)
    reasoning: str = ""
    ml_score: float = -1.0
    llm_score: float = 0.1
    blacklist_status: bool = False
    physician_fraud_ratio: float = 0.0


class CoverageResult(BaseModel):
    """Output from Agent 3 (Coverage Eligibility)."""
    coverage_status: str = Field(description="COVERED, EXCLUDED, PARTIAL, NEEDS_REVIEW")
    coverage_amount_estimate: int = 0
    exclusions_triggered: List[str] = Field(default_factory=list)
    policy_sections_cited: List[str] = Field(default_factory=list)
    rag_similarity_score: Optional[float] = None
    deterministic_deductions: Optional[dict] = None
    notes: str = ""


# ---------------------------------------------------------------------------
# LLM Client
# ---------------------------------------------------------------------------

class GenericLLMClient:
    """
    A generic OpenAI-compatible LLM client for Databricks FMAPI or local testing.
    """
    def __init__(self):
        self.workspace_url = os.environ.get("DATABRICKS_HOST", "")
        self.databricks_token = os.environ.get("DATABRICKS_TOKEN", "")
        # Fallback to OpenAI if Databricks is not configured
        self.openai_key = os.environ.get("OPENAI_API_KEY", "")
        # Try to automatically grab credentials if running inside a Databricks Notebook
        if not ((self.workspace_url and self.databricks_token) or self.openai_key):
            try:
                import IPython
                ipy = IPython.get_ipython()
                if ipy and "dbutils" in ipy.user_ns:
                    dbutils = ipy.user_ns["dbutils"]
                    ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
                    self.workspace_url = ctx.apiUrl().get()
                    self.databricks_token = ctx.apiToken().get()
            except Exception:
                pass

        if not ((self.workspace_url and self.databricks_token) or self.openai_key):
            pass # In Databricks Apps, Databricks SDK handles auth implicitly so manual keys aren't always present
        else:
            print("[LLM Client] Successfully loaded API credentials.")

    def generate(self, prompt: str, max_tokens: int = 400) -> str:
        # 1. Attempt Databricks Foundation Model API using Langchain (handles auth automatically)
        try:
            try:
                from langchain_databricks import ChatDatabricks
            except ImportError:
                from langchain_community.chat_models import ChatDatabricks
            from langchain_core.messages import HumanMessage
            
            chat = ChatDatabricks(endpoint="databricks-meta-llama-3-3-70b-instruct", max_tokens=max_tokens)
            response = chat.invoke([HumanMessage(content=prompt)])
            return response.content.strip()
        except Exception as e:
            if "404" not in str(e) and "not available" not in str(e):
                print(f"[LLM Client] Langchain/FMAPI Error: {e}")
                
        # 2. Fallback to urllib if Langchain isn't installed and we have manual tokens
        if self.workspace_url and self.databricks_token:
            try:
                url = f"{self.workspace_url.rstrip('/')}/serving-endpoints/databricks-meta-llama-3-3-70b-instruct/invocations"
                headers = {
                    "Authorization": f"Bearer {self.databricks_token}",
                    "Content-Type": "application/json"
                }
                data = {
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens
                }
                req = urllib.request.Request(url, headers=headers, data=json.dumps(data).encode('utf-8'))
                with urllib.request.urlopen(req) as response:
                    res_body = json.loads(response.read().decode('utf-8'))
                    return res_body.get("choices", [{}])[0].get("message", {}).get("content", "")
            except Exception as e:
                print(f"[LLM Client] Databricks FMAPI urllib Error: {e}")
                
        # 2. Fallback to OpenAI key (local testing)
        if self.openai_key:
            url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.openai_key}",
                "Content-Type": "application/json"
            }
            data = {
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens
            }
            req = urllib.request.Request(url, headers=headers, data=json.dumps(data).encode('utf-8'))
            try:
                with urllib.request.urlopen(req) as response:
                    res_body = json.loads(response.read().decode('utf-8'))
                    return res_body.get("choices", [{}])[0].get("message", {}).get("content", "")
            except Exception as e:
                print(f"[LLM Client] OpenAI API Error: {e}")

        # Fallback Mock if no keys provided (critical for the MVP running out of the box locally)
        print("[LLM Client] WARNING: No API keys configured. Returning mocked response.")
        if "Coverage Eligibility Agent" in prompt or "Agent 3" in prompt:
            return '{"coverage_status": "COVERED", "coverage_amount_estimate": 0, "exclusions_triggered": [], "policy_sections_cited": ["Section 4.2", "Section 5.1"], "notes": "Mocked response"}'
        elif "Fraud Detection Agent" in prompt or "Agent 2" in prompt:
            return '{"llm_fraud_score": 0.1, "narrative_signals": [], "reasoning": "Mocked response: Claim appears normal."}'
        elif "Document Intelligence Agent" in prompt or "Agent 1" in prompt:
            import re
            pol_match = re.search(r"POL-HLT-\d+(-T\d+)?", prompt)
            name_match = re.search(r"Patient \d+", prompt)
            policy = pol_match.group(0) if pol_match else "MOCK-POL"
            name = name_match.group(0) if name_match else "Mock Patient"
            return f'{{"policy_number": "{policy}", "claimant_name": "{name}", "admission_date": "2026-01-01", "discharge_date": "2026-01-05", "hospital_name": "Apollo Hospital Coimbatore", "diagnosis_icd": "J18.9", "claimed_amount": 50000, "attending_physician_registration_number": "MC-1005"}}'
        return '{"result": "Mocked fallback response"}'

llm = GenericLLMClient()
