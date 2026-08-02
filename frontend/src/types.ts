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

export interface DrugRecall {
  recall_number: string;
  event_id: string | null;
  classification: RecallClassification;
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
