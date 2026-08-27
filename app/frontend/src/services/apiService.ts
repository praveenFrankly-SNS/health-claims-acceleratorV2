const API_BASE = "http://localhost:8000";

export interface RawSilverClaim {
  claim_id: string;
  policy_number?: string;
  claimant_id?: string;
  date_of_loss?: string;
  claimed_amount?: number;
  days_since_inception?: number;
  claim_velocity?: number;
  amount_to_premium_ratio?: number;
  status?: string;
}

export interface ClaimDetailsResponse {
  claim?: Record<string, any>;
  clinical?: Record<string, any>;
  bills?: Record<string, any>[];
  policy?: Record<string, any>;
  policy_members?: Record<string, any>[];
  gold_decision?: Record<string, any>;
  documents?: {
    discharge_summary_available: boolean;
    discharge_summary_text?: string;
    hospital_bill_available: boolean;
  };
  failure_reason?: Record<string, any>;
}

export async function fetchLiveClaims(): Promise<RawSilverClaim[]> {
  try {
    const res = await fetch(`${API_BASE}/api/claims`);
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data) ? data : [];
  } catch (err) {
    console.warn("Failed to fetch live claims from Databricks API:", err);
    return [];
  }
}

export async function fetchClaimDetails(claimId: string): Promise<ClaimDetailsResponse | null> {
  try {
    const res = await fetch(`${API_BASE}/api/claims/${claimId}/details`);
    if (!res.ok) return null;
    return await res.json();
  } catch (err) {
    console.warn(`Failed to fetch details for claim ${claimId}:`, err);
    return null;
  }
}

export async function fetchReviewQueue(): Promise<any[]> {
  try {
    const res = await fetch(`${API_BASE}/api/review/queue`);
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data) ? data : [];
  } catch (err) {
    console.warn("Failed to fetch review queue from Databricks API:", err);
    return [];
  }
}

export async function fetchAuditTrail(): Promise<any[]> {
  try {
    const res = await fetch(`${API_BASE}/api/review/audit`);
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data) ? data : [];
  } catch (err) {
    console.warn("Failed to fetch audit trail from Databricks API:", err);
    return [];
  }
}

export async function fetchProviders(): Promise<any[]> {
  try {
    const res = await fetch(`${API_BASE}/api/providers`);
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data) ? data : [];
  } catch (err) {
    console.warn("Failed to fetch provider registry from Databricks API:", err);
    return [];
  }
}

export async function fetchAnalyticsMetrics(): Promise<any> {
  try {
    const res = await fetch(`${API_BASE}/api/analytics`);
    if (!res.ok) return null;
    return await res.json();
  } catch (err) {
    console.warn("Failed to fetch analytics metrics from Databricks API:", err);
    return null;
  }
}

export async function submitHumanDecision(claimId: string, decision: string, reason: string): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/api/decide`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ claim_id: claimId, decision, reason }),
    });
    return res.ok;
  } catch (err) {
    console.error("Failed to submit decision to Databricks:", err);
    return false;
  }
}
