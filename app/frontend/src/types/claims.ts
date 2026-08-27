export type ClaimStatus = "RECEIVED" | "VALIDATED" | "ASSESSED" | "UNDER_REVIEW" | "AUTO_PROCESSED" | "APPROVED" | "APPROVED_WITH_CONDITIONS" | "INFO_REQUESTED" | "INVESTIGATION" | "REJECTED";

export type RiskLevel = "HIGH" | "MEDIUM" | "LOW";

export type ReviewType = "Fraud Review" | "Medical Review" | "Coverage Review" | "Document Review" | "High Value Review";

export type AssignedRole = "Claims Specialist" | "Medical Reviewer" | "Fraud / SIU Investigator" | "Claims Manager";

export interface PatientInfo {
  id: string;
  name: string;
  age: number;
  gender: string;
  memberId: string;
  coverageStartDate: string;
  priorClaimsCount: number;
  totalPriorClaimed: number;
}

export interface PolicyInfo {
  policyNumber: string;
  policyType: "FLOATER" | "INDIVIDUAL";
  planTier: "Silver" | "Gold" | "Premium";
  sumInsured: number;
  remainingSumInsured: number;
  inceptionDate: string;
  status: "ACTIVE" | "EXPIRED" | "SUSPENDED";
  copayTerms: string;
  roomRentCapPct: number;
}

export interface HospitalInfo {
  id: string;
  name: string;
  city: string;
  networkStatus: "IN-NETWORK" | "OUT-OF-NETWORK";
  historicalRiskLevel: RiskLevel;
  totalClaimsCount: number;
  avgClaimAmount: number;
  industryAvgAmount: number;
  highRiskRatePct: number;
  repeatedProcedureAlerts: number;
  documentationIssuesCount: number;
}

export interface BillItem {
  id: string;
  description: string;
  expenseType: "ROOM_RENT" | "ICU" | "SURGEON_FEE" | "MEDICINES" | "DIAGNOSTICS" | "IMPLANTS" | "OTHER";
  amount: number;
  benchmarkAmount: number;
  isExceedingLimit: boolean;
}

export interface AIAssessment {
  fraudScorePct: number;
  fraudRiskLevel: RiskLevel;
  fraudWhyBullets: string[];
  medicalRiskLevel: RiskLevel;
  medicalNotes: string;
  coverageStatus: "COVERED" | "PARTIALLY_ELIGIBLE" | "EXCLUDED" | "NEEDS_REVIEW";
  coverageChecks: {
    treatmentCovered: boolean;
    policyActive: boolean;
    sumInsuredAvailable: boolean;
    roomRentCapExceeded: boolean;
    copayApplicable: boolean;
    waitingPeriodViolated: boolean;
  };
  duplicateCheck: "FLAGGED" | "CLEAN";
  providerRiskLevel: RiskLevel;
  reserveEstimate: number;
  systemRecommendation: string;
  recommendationReason: string;
  confidenceScorePct: number;
}

export interface FinancialBreakdown {
  claimedAmount: number;
  roomRentExcessDeduction: number;
  copayDeduction: number;
  sublimitExcessDeduction: number;
  nonAdmissibleDeduction: number;
  netAdmissibleAmount: number;
  reserveEstimate: number;
}

export interface ClaimDocument {
  id: string;
  title: string;
  type: "BILL" | "DISCHARGE_SUMMARY" | "PRE_AUTH" | "CLINICAL_NOTES" | "DIAGNOSTIC_REPORT";
  fileName: string;
  fileSize: string;
  uploadedAt: string;
  status: "VERIFIED" | "INCONSISTENT" | "PENDING";
}

export interface TimelineEvent {
  id: string;
  timestamp: string;
  stage: string;
  title: string;
  description: string;
  actor: string;
  badgeType?: "info" | "warning" | "success" | "danger";
}

export interface Claim {
  claimId: string;
  submissionDate: string;
  claimType: "CASHLESS" | "REIMBURSEMENT";
  status: ClaimStatus;
  riskLevel: RiskLevel;
  riskScorePct: number;
  reviewType: ReviewType;
  priority: "HIGH" | "MEDIUM" | "LOW";
  assignedRole: AssignedRole;
  assignedToName: string;
  slaRemainingHours: number;
  agingHours: number;
  
  patient: PatientInfo;
  policy: PolicyInfo;
  hospital: HospitalInfo;
  
  diagnosis: string;
  icdCode: string;
  treatmentProcedure: string;
  admissionDate: string;
  dischargeDate: string;
  losDays: number;
  attendingDoctor: string;
  doctorRegNo: string;
  
  claimedAmount: number;
  financials: FinancialBreakdown;
  aiAssessment: AIAssessment;
  
  billItems: BillItem[];
  documents: ClaimDocument[];
  timeline: TimelineEvent[];
  
  finalDecision?: {
    action: "APPROVE" | "APPROVE_CONDITIONAL" | "INFO_REQUESTED" | "INVESTIGATE" | "REJECT";
    decidedBy: string;
    decidedAt: string;
    remarks: string;
    admissibleAmountApproved: number;
  };
}

export interface AuditLogEntry {
  id: string;
  timestamp: string;
  claimId: string;
  patientName: string;
  actorName: string;
  actorRole: string;
  action: string;
  decisionStatus: ClaimStatus;
  notes: string;
  financialImpact: number;
}
