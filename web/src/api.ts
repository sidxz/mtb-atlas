/**
 * The only way this app reaches data. Types mirror the Pydantic models in
 * atlas/api.py; if they drift, the API's /openapi.json is the arbiter.
 */

const BASE = import.meta.env.VITE_API_BASE ?? "/api";

export type Essentiality = "ES" | "ESD" | "GD" | "NE" | "GA" | "Uncertain";

export interface TargetSummary {
  rv_id: string;
  gene_name: string | null;
  product: string | null;
  category: string | null;
  start: number;
  stop: number;
  strand: string;
  length: number | null;
  uniprot_acc: string | null;
  essentiality: Essentiality | null;
  essentiality_label: string | null;
  feature: string;
  essentiality_essential: boolean;
  essentiality_fitness_cost: boolean;
  essentiality_condition: string | null;
  ta_sites: number | null;
  n_pdb: number;
  best_resolution: number | null;
  has_predicted: boolean;
  plddt_mean: number | null;
  n_activities: number;
  n_compounds: number;
  best_pchembl: number | null;
  n_whole_cell: number;
  best_whole_cell_pchembl: number | null;
  chembl_evidence: "direct" | "orthologue" | null;
  in_who_catalogue: boolean;
  n_variants_associated: number;
  n_variants_mappable: number;
  resistance_drugs: string[];
  /** CRISPRi knockdown. More negative is more vulnerable. */
  vulnerability_index: number | null;
  vi_lower: number | null;
  vi_upper: number | null;
  vulnerability_certain: boolean;
  crispr_essential: boolean;
  /** The drug that already targets this gene, per Bosch 2021. */
  antibacterial: string | null;
  human_homolog: boolean;
  close_human_homolog: boolean;
  human_homolog_gene: string | null;
  human_homolog_acc: string | null;
  human_homolog_identity: number | null;
  human_homolog_evalue: number | null;
  n_partners: number;
  top_partner_score: number | null;
  has_structure: boolean;
  has_ligands: boolean;
  structural_gap: boolean;
  conflict: boolean;
  /** Drugs a source says act on this gene's own protein (ChEMBL mechanism, Bosch 2021). */
  n_drugs: number;
  /** Their best phase *for tuberculosis*, not for any indication. */
  best_drug_phase: number | null;
  drug_names: string[];
  /** Drugs that reach this gene only as one member of the complex they act on. */
  n_complex_drugs: number;
  n_trials: number;
  has_clinical_drug: boolean;
  /** From the UniProt entry; null where there is no protein (RNA genes). */
  n_transmembrane: number | null;
  n_references: number | null;
}

export interface StructureComponent {
  comp_id: string;
  name: string | null;
  formula_weight: number | null;
  role: "ligand" | "cofactor" | "incidental";
  chains: string[];
  /** False when this component sits on another protein's chain in the same entry. */
  on_chain: boolean;
}

export interface Structure {
  pdb_id: string;
  title: string | null;
  method: string | null;
  resolution: number | null;
  released: string | null;
  chains: string[];
  entity_description: string | null;
  components: StructureComponent[];
  /** Ligands on this protein's own chains. */
  ligand_ids: string[];
  n_ligands: number;
  /** In the entry, but bound to another chain: shown, never counted. */
  ligand_ids_elsewhere: string[];
}

export interface ChemblTarget {
  target_id: string;
  target_type: string | null;
  pref_name: string | null;
  evidence: "direct" | "orthologue";
  via_accession: string | null;
  via_organism: string | null;
  via_gene: string | null;
  uniref_cluster: string | null;
  identity_level: string | null;
  cluster_size: number | null;
}

export interface Activity {
  activity_id: number | null;
  molecule_chembl_id: string | null;
  target_chembl_id: string | null;
  target_organism: string | null;
  evidence: "direct" | "orthologue" | "whole_cell";
  standard_type: string | null;
  standard_relation: string | null;
  standard_value: number | null;
  standard_units: string | null;
  pchembl_value: number | null;
  assay_chembl_id: string | null;
  assay_description: string | null;
  document_chembl_id: string | null;
  document_year: number | null;
  data_validity_comment: string | null;
  potential_duplicate: boolean;
}

export interface Compound {
  molecule_chembl_id: string;
  pref_name: string | null;
  molecule_type: string | null;
  max_phase: number | null;
  first_approval: number | null;
  smiles: string | null;
  inchi_key: string | null;
  mw: number | null;
  alogp: number | null;
  hba: number | null;
  hbd: number | null;
  psa: number | null;
  rotatable_bonds: number | null;
  aromatic_rings: number | null;
  ro5_violations: number | null;
  qed: number | null;
}

export interface Variant {
  gene: string;
  mutation: string;
  variant: string;
  drug: string;
  grading: string;
  associated: boolean;
  tier: string | null;
  effect: string | null;
  genomic_position: string | null;
  residue_position: number | null;
  residue_label: string | null;
}

export interface PredictedStructure {
  uniprot_acc: string;
  entry_id: string | null;
  version: number | null;
  created: string | null;
  plddt_mean: number | null;
  plddt_very_high: number | null;
  plddt_confident: number | null;
  plddt_low: number | null;
  plddt_very_low: number | null;
  cif_url: string | null;
  pae_url: string | null;
}

export interface TargetDetail extends TargetSummary {
  protein_name: string | null;
  acc_status: string | null;
  shares_accession_with: string[];
  is_pseudogene: boolean;
  alphafold: PredictedStructure | null;
  structures: Structure[];
  chembl_targets: ChemblTarget[];
  activities: Activity[];
  whole_cell: Activity[];
  compounds: Compound[];
  variants: Variant[];
  partners: Partner[];
  interpro_ids: string[];
  pfam_ids: string[];
  go_ids: string[];
  ec_numbers: string[];
  /** UniProt's biology: curated if reviewed, automatic if not. Null or empty: UniProt is silent. */
  reviewed: boolean | null;
  function: string | null;
  subcellular_location: string | null;
  locations: string[];
  signal_peptide: boolean;
  pathways: string[];
  reactions: string[];
  rhea_ids: string[];
  cofactors: string[];
  go_process: string[];
  go_function: string[];
  go_component: string[];
  disruption_phenotype: string | null;
  pubmed_ids: string[];
  protein_existence: string | null;
  annotation_score: number | null;
  drugs: GeneDrug[];
  trials: GeneTrial[];
  /** What the atlas does NOT know, stated rather than left as a blank cell. */
  absences: string[];
}

/**
 * How a drug reaches a gene. Only `mechanism` and `bosch_2021` say the drug acts
 * on this gene's own protein; a complex member is one subunit of what the drug
 * acts on, and WHO resistance is not target engagement.
 */
export type DrugLink = "mechanism" | "mechanism_complex" | "bosch_2021" | "who_resistance";

export interface Ref {
  type: string;
  id: string;
  url: string | null;
}

interface LinkDetail {
  link: DrugLink;
  target_chembl_id: string | null;
  target_name: string | null;
  n_target_components: number | null;
  shared_accession: boolean;
  /** What the source actually said: the mechanism, Bosch's text, the WHO drug. */
  source_text: string | null;
  n_variants: number | null;
}

export interface GeneDrug extends LinkDetail {
  molecule_chembl_id: string;
  pref_name: string | null;
  max_phase_tb: number | null;
  max_phase: number | null;
  first_approval: number | null;
  molecule_type: string | null;
}

export interface TrialSummary {
  nct_id: string;
  brief_title: string | null;
  acronym?: string | null;
  phases: string[];
  phase_max: number | null;
  status: string | null;
  start_date: string | null;
  completion_date?: string | null;
  lead_sponsor: string | null;
  enrollment?: number | null;
  has_results: boolean;
}

export interface GeneTrial extends TrialSummary {
  drugs: string[];
}

export interface DrugSummary {
  molecule_chembl_id: string;
  pref_name: string | null;
  synonyms: string[];
  max_phase_tb: number | null;
  max_phase: number | null;
  first_approval: number | null;
  molecule_type: string | null;
  atc_codes: string[];
  acts_on_mtb: boolean;
  host_targeted: boolean;
  target_organisms: string[];
  mechanisms_of_action: string[];
  genes: { rv_id: string; gene_name: string | null }[];
  n_trials: number;
}

export interface Mechanism {
  mechanism_of_action: string | null;
  action_type: string | null;
  mechanism_comment: string | null;
  direct_interaction: boolean;
  target_chembl_id: string | null;
  target_name: string | null;
  target_type: string | null;
  target_organism: string | null;
  target_tax_id: number | null;
  component_accessions: string[];
  refs: Ref[];
}

export interface DrugGene extends LinkDetail {
  rv_id: string;
  gene_name: string | null;
  product: string | null;
  essentiality: string | null;
  vulnerability_index: number | null;
  vulnerability_certain: boolean;
}

export interface DrugTrial extends TrialSummary {
  via_chembl_ref: boolean;
  via_intervention_name: boolean;
  matched_names: string[];
}

export interface DrugDetail {
  molecule_chembl_id: string;
  pref_name: string | null;
  molecule_type: string | null;
  max_phase_tb: number | null;
  max_phase: number | null;
  first_approval: number | null;
  synonyms: string[];
  salt_chembl_ids: string[];
  tb_indications: string[];
  atc_codes: string[];
  nct_ids: string[];
  label_refs: Ref[];
  acts_on_mtb: boolean;
  host_targeted: boolean;
  smiles: string | null;
  mw: number | null;
  alogp: number | null;
  mechanisms: Mechanism[];
  genes: DrugGene[];
  trials: DrugTrial[];
  bioactivity: {
    n_protein: number;
    best_protein_pchembl: number | null;
    n_whole_cell: number;
    best_whole_cell_pchembl: number | null;
  };
}

export interface TrialDrug {
  molecule_chembl_id: string;
  pref_name: string | null;
  via_chembl_ref: boolean;
  via_intervention_name: boolean;
}

export interface Trial extends TrialSummary {
  official_title: string | null;
  why_stopped: string | null;
  primary_completion_date: string | null;
  first_posted: string | null;
  last_update: string | null;
  allocation: string | null;
  primary_purpose: string | null;
  sponsor_class: string | null;
  collaborators: string[];
  conditions: string[];
  interventions: { type: string | null; name: string | null; other_names: string[] }[];
  arms: { label: string | null; type: string | null; interventions: string[] }[];
  countries: string[];
  drugs: TrialDrug[];
}

export interface TrialDetail extends Omit<Trial, "drugs"> {
  drugs: (TrialDrug & { matched_names: string[]; max_phase_tb: number | null })[];
  genes: { rv_id: string; gene_name: string | null; link: DrugLink; drug: string | null }[];
}

export interface Page<T> {
  total: number;
  limit: number;
  offset: number;
  items: T[];
}

export interface Partner {
  rv_id: string;
  gene_name: string | null;
  combined_score: number;
  experimental: number;
  database: number;
  textmining: number;
  coexpression: number;
}

export interface Meta {
  counts: Record<string, number>;
  sources: { name: string; version: string; licence: string; retrieved: string }[];
  caveats: string[];
}

export interface TargetQuery {
  q?: string;
  essentiality?: string[];
  category?: string[];
  has_structure?: boolean;
  has_predicted?: boolean;
  has_ligands?: boolean;
  in_who_catalogue?: boolean;
  structural_gap?: boolean;
  conflict?: boolean;
  crispr_essential?: boolean;
  vulnerability_certain?: boolean;
  human_homolog?: boolean;
  close_human_homolog?: boolean;
  min_pchembl?: number;
  max_vulnerability_index?: number;
  sort?: string;
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
}

async function get<T>(path: string, params?: Record<string, unknown>): Promise<T> {
  const url = new URL(`${BASE}${path}`, window.location.origin);
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => url.searchParams.append(key, String(v)));
    else url.searchParams.set(key, String(value));
  }
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText} from ${path}`);
  }
  return (await response.json()) as T;
}

export const api = {
  meta: () => get<Meta>("/meta"),
  targets: (query: TargetQuery) =>
    get<{ total: number; limit: number; offset: number; items: TargetSummary[] }>(
      "/targets",
      query as Record<string, unknown>,
    ),
  target: (rvId: string) => get<TargetDetail>(`/targets/${rvId}`),
  compound: (id: string) => get<Compound & { activities: Activity[] }>(`/compounds/${id}`),
  drugs: () => get<Page<DrugSummary>>("/drugs", { limit: 1000 }),
  drug: (id: string) => get<DrugDetail>(`/drugs/${id}`),
  trials: () => get<Page<Trial>>("/trials", { limit: 2000 }),
  trial: (nctId: string) => get<TrialDetail>(`/trials/${nctId}`),
};
