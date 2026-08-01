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
