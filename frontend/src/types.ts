export interface CommunityHealthDataSource {
  name: string;
  dataset_name: string;
  dataset_url: string;
  retrieved_at: string;
  estimate_type: string;
}

export interface CommunityHealthMeasure {
  measure_id: string;
  measure: string;
  category: string;
  latest_year: number;
  county_count: number;
}

export interface CommunityHealthMeasureCatalog {
  items: CommunityHealthMeasure[];
  total: number;
  source: CommunityHealthDataSource;
}

export interface CountyHealthEstimate {
  year: number;
  state: string;
  state_name: string;
  county: string;
  county_fips: string;
  measure_id: string;
  measure: string;
  category: string;
  prevalence_percent: number;
  low_confidence_limit: number;
  high_confidence_limit: number;
  population: number;
  adult_population: number;
  latitude: number;
  longitude: number;
}

export interface CountyHealthPage {
  items: CountyHealthEstimate[];
  total: number;
  limit: number;
  offset: number;
  state: string;
  measure_id: string;
  source: CommunityHealthDataSource;
}

export type RecallClassification = "Class I" | "Class II" | "Class III";
export type RecallRecordClassification = RecallClassification | "Not Yet Classified";

export interface DrugRecall {
  recall_number: string | null;
  event_id: string | null;
  classification: RecallRecordClassification;
  status: "Ongoing" | "Completed" | "Terminated" | null;
  recalling_firm: string;
  city: string | null;
  state: string | null;
  country: string | null;
  product_description: string;
  reason_for_recall: string;
  voluntary_mandated: string | null;
  distribution_pattern: string;
  product_quantity: string | null;
  recall_initiation_date: string | null;
  report_date: string;
}

export interface DrugRecallDataSource {
  name: string;
  dataset_name: string;
  dataset_url: string;
  retrieved_at: string;
  last_updated: string;
  disclaimer: string;
  terms_url: string;
  license_url: string;
}

export interface DrugRecallPage {
  items: DrugRecall[];
  total: number;
  limit: number;
  offset: number;
  classification: RecallClassification | null;
  source: DrugRecallDataSource;
}

export type HospitalIngestionRunState = "started" | "succeeded" | "failed";
export type HospitalIngestionHealthReason =
  | "healthy"
  | "ingestion_in_progress"
  | "no_runs"
  | "latest_run_failed"
  | "stale";

export interface HospitalIngestionStatus {
  run_id: string;
  source_dataset_id: string;
  status: HospitalIngestionRunState;
  retrieved_at: string;
  started_at: string;
  finished_at: string | null;
  expected_count: number | null;
  fetched_count: number;
  upserted_count: number;
  pages: number;
  request_attempts: number;
  error_type: string | null;
  error_message: string | null;
  latest_successful_retrieved_at: string | null;
  freshness_seconds: number | null;
  stale_after_seconds: number;
  is_stale: boolean;
}

export interface HospitalIngestionHealth {
  healthy: boolean;
  reason: HospitalIngestionHealthReason;
  latest_run: HospitalIngestionStatus | null;
}
