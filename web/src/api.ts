/**
 * The only way this app reaches data. Types mirror the Pydantic models in
 * atlas/api.py; if they drift, the API's /openapi.json is the arbiter.
 */

const BASE = import.meta.env.VITE_API_BASE ?? "/api";

export type Essentiality = "ES" | "ESD" | "GD" | "NE" | "GA" | "Uncertain";

/**
 * How far chemical interrogation of a protein has got in the public record.
 * Derived in the roll-up from columns already on the row; it measures nothing
 * of its own. The levels are not cumulative — a gene can hold clinical-stage
 * chemical matter and no assay against its purified protein — and NULL means
 * the clinical or screening layer is not built in this store.
 */
export type ValidationStatus =
  | "clinically_validated"
  | "clinical_stage"
  | "biochemically_interrogated"
  | "annotated_target"
  | "screened"
  | "genetically_nominated"
  | "not_interrogated";

export interface TargetSummary {
  rv_id: string;
  validation_status: ValidationStatus | null;
  shared_accession: boolean;
  n_chembl_targets: number;
  n_complex_assays: number;
  n_pdb_with_ligand: number;
  /**
   * Screening campaigns reaching this protein. Null, not zero, where the
   * screening layer is not built in this store. `n_screen_actives` counts only
   * campaigns that stated an outcome, so it shares no denominator with
   * `n_target_screens` and must not be divided by it.
   */
  n_target_screens: number | null;
  n_complex_screens: number | null;
  max_screen_compounds: number | null;
  n_screen_actives: number | null;
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
  /**
   * Griffin 2011, cholesterol vs glycerol. Null where the locus was never
   * screened; `measured` false where it was and took no insertions to compare,
   * which is true of every in-vitro-essential gene.
   */
  cholesterol_measured: boolean | null;
  cholesterol_log2_ratio: number | null;
  cholesterol_p: number | null;
  cholesterol_required: boolean | null;
  required_in_vivo: boolean | null;
  n_pdb: number;
  best_resolution: number | null;
  /**
   * A structure to work from that is not of this protein: a mycobacterial
   * neighbour's entry, reached by homology. Counted apart from `n_pdb`, which
   * stays the number of entries on this gene's own accession, so a zero there
   * still means "none of its own".
   *
   * `same_sequence_structure` is the stronger claim: an identical sequence
   * deposited under another accession (CDC 1551, H37Ra, M. bovis), which the
   * atlas missed only because the key is the H37Rv one.
   */
  n_orthologue_pdb: number;
  n_orthologue_pdb_with_ligand: number;
  best_orthologue_resolution: number | null;
  closest_orthologue_gene: string | null;
  closest_orthologue_organism: string | null;
  closest_orthologue_identity: number | null;
  closest_orthologue_coverage: number | null;
  same_sequence_structure: boolean;
  /**
   * Has a drug ever been filed against this fold? Drugs ChEMBL records against
   * another single protein carrying one of this gene's Pfam domains.
   *
   * Not a druggability score -- nothing public supplies one -- and not a drug
   * that acts on this gene, which is `n_drugs`. `null` where UniProt annotates
   * no domain: nothing to look up is not nothing found.
   *
   * `n_precedent_human_target` is how many of the approved ones act on a human
   * protein, where tractable chemistry and a selectivity problem are the same
   * fact. `n_precedent_complex` is filings against a complex or protein family
   * containing such a protein -- shown, never counted, because ChEMBL files
   * the ribosome's 45 approved drugs against every subunit.
   *
   * `precedent_domain_genes` is how many Mtb genes share the domain, because a
   * shared domain is not a shared binding site.
   */
  n_precedent_approved: number | null;
  n_precedent_clinical: number | null;
  n_precedent_human_target: number | null;
  n_precedent_complex: number | null;
  precedent_pfam: string | null;
  precedent_pfam_name: string | null;
  precedent_domain_genes: number | null;
  precedent_example: string | null;
  has_predicted: boolean;
  plddt_mean: number | null;
  n_activities: number;
  n_compounds: number;
  best_pchembl: number | null;
  n_whole_cell: number;
  /**
   * ChEMBL's own pchembl_value, which it computes for affinity endpoints only.
   * It is null on every MIC row, so this covers far fewer genes than
   * `best_pmic` and is NOT the MIC. Kept because a whole-cell IC50 is real.
   */
  best_whole_cell_pchembl: number | null;
  /**
   * -log10(MIC in mol/L). The whole-cell number a chemist means. Censored
   * MICs (`> top concentration`) are excluded and counted in `n_mic_censored`,
   * because "did not inhibit at 128 uM" is not a potency of 128 uM.
   */
  best_pmic: number | null;
  median_pmic: number | null;
  n_mic: number;
  n_mic_censored: number;
  n_resistant_panel: number;
  whole_cell_conditions: WholeCellCondition[];
  /** Largest single published assay by distinct compounds. */
  max_assay_compounds: number;
  chembl_evidence: "direct" | "orthologue" | null;
  in_who_catalogue: boolean;
  n_variants_associated: number;
  n_variants_mappable: number;
  resistance_drugs: string[];
  /**
   * Functional redundancy: could a second copy cover for this target?
   * `close_paralog` is stricter than `close_human_homolog` on purpose — it
   * needs coverage as well as identity, because a backup has to be the same
   * protein rather than merely share a domain with it.
   */
  has_paralog: boolean;
  n_paralogs: number;
  close_paralog: boolean;
  n_close_paralogs: number;
  /** The nearest *backup*. Null when relatives exist but none is full-length. */
  closest_paralog_gene: string | null;
  closest_paralog_identity: number | null;
  /** The nearest *relative*, by bitscore. Usually populated even with no backup. */
  nearest_relative_gene: string | null;
  nearest_relative_identity: number | null;
  nearest_relative_coverage: number | null;

  /** CRISPRi knockdown. More negative is more vulnerable. */
  vulnerability_index: number | null;
  vi_lower: number | null;
  vi_upper: number | null;
  vulnerability_certain: boolean;
  crispr_essential: boolean;
  /**
   * The same CRISPRi series in HN878, a clinical isolate. `hn878_delta_vi` runs
   * HN878 minus H37Rv, so positive means *less* vulnerable in the clinic. Null
   * where the strain sheet never covered the locus, and null delta where the
   * authors reported no differential for it -- not a difference of zero.
   */
  hn878_vulnerability_index: number | null;
  hn878_vi_certain: boolean | null;
  hn878_delta_vi: number | null;
  hn878_delta_vi_norm: number | null;
  hn878_differential_reported: boolean;
  /**
   * Whether a way to measure this protein has been published — a different
   * question from whether anyone has hit it. ChEMBL assays on the Mtb protein
   * itself; orthologue and whole-cell measurements are not counted.
   */
  n_protein_assays: number;
  latest_protein_assay_year: number | null;
  protein_assay_example: string | null;
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
  /**
   * Drugs a source says act on this gene's own protein (ChEMBL mechanism, Bosch
   * 2021). Null, not zero, where the clinical layer is not built in this store.
   */
  n_drugs: number | null;
  /** Their best phase *for tuberculosis*, not for any indication. */
  best_drug_phase: number | null;
  drug_names: string[] | null;
  /** Drugs that reach this gene only as one member of the complex they act on. */
  n_complex_drugs: number | null;
  n_trials: number | null;
  has_clinical_drug: boolean | null;
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

/** One mycobacterial neighbour's PDB entry, with the homology that reached it. */
export interface OrthologueStructure {
  via_acc: string;
  via_gene: string | null;
  via_organism: string | null;
  via_taxon: string | null;
  /** `same_sequence` is the protein itself under another accession; `orthologue` is a relative. */
  relation: "same_sequence" | "orthologue";
  identity: number;
  coverage: number;
  evalue: number | null;
  bitscore: number | null;
  pdb_id: string;
  title: string | null;
  method: string | null;
  resolution: number | null;
  released: string | null;
  entity_description: string | null;
  ligand_ids: string[];
  n_ligands: number;
}

/** One ChEMBL drug-target mechanism, reached by a Pfam domain this gene shares. */
export interface DrugPrecedent {
  pfam_id: string;
  pfam_name: string | null;
  /** The protein the drug was actually filed against, never this gene's own. */
  accession: string | null;
  molecule_chembl_id: string;
  molecule_name: string | null;
  /** 4 approved, 1-3 clinical, -1 ChEMBL does not know. */
  max_phase: number | null;
  target_chembl_id: string;
  target_name: string | null;
  /** Only `SINGLE PROTEIN` is counted; a complex or family is shown and not. */
  target_type: string | null;
  organism: string | null;
  tax_id: number | null;
  action_type: string | null;
  mechanism_of_action: string | null;
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

/** The growth condition an MIC was measured under, read from the assay prose. */
export type AssayCondition =
  | "caseum"
  | "intracellular"
  | "non_replicating"
  | "alt_carbon"
  | "nutrient_stress"
  | "standard_media"
  /** The deposit named no medium. NOT the same as standard media. */
  | "unspecified";

export interface WholeCellCondition {
  condition: AssayCondition;
  n: number;
  n_with_pmic: number;
  best_pmic: number | null;
}

export interface ProteinAssay {
  assay_chembl_id: string;
  target_chembl_id: string;
  description: string | null;
  n_compounds: number;
  n_measurements: number;
  endpoint_types: string[];
  latest_year: number | null;
  document_ids: string[];
  source_version: string | null;
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
  /** -log10(MIC in mol/L); null for a censored or non-MIC row. */
  pmic: number | null;
  /** Which unit conversion produced `pmic`, including the MW if one was used. */
  pmic_basis: string | null;
  /** Null on protein assays: a biochemical assay has no growth medium. */
  assay_condition: AssayCondition | null;
  /** Strain, not medium: an MDR or clinical-isolate panel. */
  resistant_panel: boolean;
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

/** A campaign that reached this gene. `own` is its protein; the rest is shown, not counted. */
export interface GeneScreen {
  own: boolean;
  via_complex: boolean;
  screen_id: string;
  title: string | null;
  depositor: string | null;
  source: string;
  year: number | null;
  n_stages: number;
  n_tested: number | null;
  library_size_stated: number | null;
  outcome_stated: boolean;
  n_active: number | null;
  n_inactive: number | null;
  modalities: string[];
}

export interface TargetDetail extends TargetSummary {
  screens: GeneScreen[];
  protein_name: string | null;
  acc_status: string | null;
  shares_accession_with: string[];
  is_pseudogene: boolean;
  alphafold: PredictedStructure | null;
  structures: Structure[];
  orthologue_structures: OrthologueStructure[];
  drug_precedent: DrugPrecedent[];
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
  bound_ligands: BoundLigand[];
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
  /** Significant (q < 0.05) results in an annotated MtbTnDB condition screen. */
  conditions: ConditionHit[];
  /** The same, but in a knockout background: an interaction, not a condition. */
  interactions: ConditionHit[];
  /** How many annotated condition screens could and could not measure this gene. */
  tnseq_coverage: { measured: number; unmeasured: number };
  /** What the atlas does NOT know, stated rather than left as a blank cell. */
  absences: string[];
}

export interface ConditionHit {
  screen_id: string;
  /** in_vitro | in_vivo | in_cell, or null where the authors record none. */
  condition_class: string | null;
  description: string | null;
  study: string;
  /** The control library came from a different study: a batch-effect caveat. */
  cross_study: boolean;
  stress: string | null;
  carbon_source: string | null;
  medium: string | null;
  mouse_strain: string | null;
  mtb_strain: string | null;
  /** The knockout background, for an interaction screen. */
  interaction: string | null;
  log2fc: number;
  q_value: number;
  measured: boolean;
  n_ta_sites: number | null;
  sum_control: number | null;
  sum_experimental: number | null;
}

/** What was varied, in the authors' own words, shortest useful field first. */
export function conditionLabel(hit: ConditionHit): string {
  return (
    hit.stress ??
    hit.carbon_source ??
    hit.mouse_strain ??
    hit.medium ??
    hit.description ??
    hit.screen_id
  );
}

/**
 * How a drug reaches a gene. Only `mechanism` and `bosch_2021` say the drug acts
 * on this gene's own protein; a complex member is one subunit of what the drug
 * acts on, and WHO resistance is not target engagement.
 */
export type DrugLink =
  | "mechanism"
  | "mechanism_complex"
  | "bosch_2021"
  | "structure"
  | "who_resistance";

/** A component modelled on this protein's own chain, named and tied to a molecule. */
export interface BoundLigand {
  comp_id: string;
  name: string | null;
  formula_weight: number | null;
  inchikey: string | null;
  smiles: string | null;
  molecule_chembl_id: string | null;
  drug_name: string | null;
  max_phase_tb: number | null;
  best_pchembl: number | null;
}

export interface Ref {
  type: string;
  id: string;
  url: string | null;
}

interface LinkDetail {
  link: DrugLink;
  target_chembl_id: string | null;
  target_name: string | null;
  /** Accessions on ChEMBL's target, which for a ribosome is fewer than its components. */
  n_target_accessions: number | null;
  target_type: string | null;
  shared_accession: boolean;
  /** What the source actually said: the mechanism, Bosch's text, the WHO drug. */
  source_text: string | null;
  n_variants: number | null;
}

export interface GeneDrug extends LinkDetail {
  molecule_chembl_id: string;
  pref_name: string | null;
  /** Drawn in the browser; see Structure.tsx. Nothing is stored. */
  smiles: string | null;
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
  /** Drawn in the browser; see Structure.tsx. Nothing is stored. */
  smiles: string | null;
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
  inchi_key: string | null;
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
  genes: { rv_id: string; gene_name: string | null }[];
}

/** One thing the atlas holds, named well enough to pick from a list. */
export interface Hit {
  id: string;
  label: string;
  detail: string | null;
}

export type SearchResults = Record<
  "genes" | "drugs" | "trials" | "compounds" | "screens",
  Hit[]
>;

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

/** One molecule as hit triage asks for it: what it touches, and how hard. */
export interface CompoundDetail extends Compound {
  genes: {
    rv_id: string;
    gene_name: string | null;
    product: string | null;
    essentiality: string | null;
    vulnerability_index: number | null;
    vulnerability_certain: boolean;
    evidence: "direct" | "orthologue";
    via_organism: string | null;
    n_activities: number;
    best_pchembl: number | null;
  }[];
  activities: Activity[];
  whole_cell: Activity[];
  drug: DrugSummary | null;
  /** Every campaign stage that tested it, with the outcome as the source gave it. */
  tested_in: (ScreenResult & { screen_title: string | null; screen_source: string; year: number | null })[];
}

export interface Meta {
  counts: Record<string, number>;
  sources: { name: string; version: string; licence: string; retrieved: string }[];
  caveats: string[];
}

export interface TargetQuery {
  q?: string;
  validation_status?: string[];
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

/** A gene a campaign reaches. `own` is its own protein; `via_complex` is shown, never counted. */
export interface ScreenGene {
  rv_id: string;
  gene_name: string | null;
  own: boolean;
  via_complex: boolean;
}

export interface ScreenTarget {
  accession: string | null;
  name: string | null;
  accession_kind: string | null;
  rv_ids: string[];
}

export interface ScreenSummary {
  source_version?: string;
  retrieved_at?: string;
  screen_id: string;
  aid: string | null;
  title: string | null;
  depositor: string | null;
  source: string;
  year: number | null;
  n_stages: number;
  /** Deposited: SIDs for PubChem, distinct compounds for ChEMBL. Not `library_size_stated`. */
  n_tested: number | null;
  library_size_stated: number | null;
  /** False where the source stated no activity call at all. Then the counts below are NULL. */
  outcome_stated: boolean;
  n_active: number | null;
  n_inactive: number | null;
  modalities: string[];
  document_chembl_id: string | null;
  pubmed_id: string | null;
  genes: ScreenGene[];
  /** Proteins this atlas could not key to a locus: another strain, a GenBank id, a PDB chain. */
  unplaced_targets: ScreenTarget[];
}

export interface ScreenStage {
  stage_id: string;
  stage: string | null;
  modality: string | null;
  description: string | null;
  derived: boolean;
  strain: string | null;
  assay_condition: string | null;
  n_tested: number | null;
  n_active: number | null;
  n_rows: number | null;
  n_compounds: number | null;
  n_active_rows: number | null;
  n_inactive_rows: number | null;
  n_inconclusive_rows: number | null;
  n_no_call_rows: number | null;
  endpoints: string[] | null;
}

/** One result row as the source deposited it: a sample or an activity, not a compound. */
export interface ScreenResult {
  source?: string;
  source_version?: string;
  retrieved_at?: string;
  stage_id: string;
  screen_id: string;
  stage: string | null;
  /** A computed ratio, which holds no funnel position. */
  derived?: boolean;
  modality: string | null;
  pubchem_cid: string | null;
  pubchem_sid: string | null;
  molecule_chembl_id: string | null;
  pref_name: string | null;
  smiles: string | null;
  /** NULL means the source stated no call. It does not mean inactive. */
  outcome: string | null;
  activity_score: number | null;
  endpoint: string | null;
  standard_relation: string | null;
  standard_value: number | null;
  standard_units: string | null;
  activity_comment: string | null;
  /** The row's own identity: PubChem numbers its table rows, ChEMBL its activities. */
  result_tag: number | null;
  activity_id: number | null;
}

export interface ScreenDetail extends ScreenSummary {
  stages: ScreenStage[];
  genes: (ScreenGene & { product: string | null; essentiality: string | null })[];
}

export interface ScreenPage {
  n_own_genes: number;
  n_genes: number;
  total: number;
  items: ScreenSummary[];
  /** How many stages carry the classifier's default label, so a funnel can say so. */
  stage_labels: {
    n_stages: number;
    n_primary: number;
    n_modality_other: number;
    n_modality_unclassified: number;
  };
  n_unplaced: number;
  not_ingested: string[];
}

/** One compound and what was measured on it. A NULL count is unmeasured, never zero. */
export interface HitProfile {
  molecule_chembl_id: string;
  pref_name: string | null;
  smiles: string | null;
  n_papers: number;
  first_year: number | null;
  latest_year: number | null;
  n_mtb_whole_cell: number | null;
  n_mtb_protein: number | null;
  n_other_pathogen: number | null;
  n_cytotox: number | null;
  n_adme: number | null;
  n_in_vivo: number | null;
  n_other: number | null;
  /** The authors' own cytotox/potency ratio. Bounds are counted apart, never averaged. */
  n_selectivity: number | null;
  selectivity_min: number | null;
  /** What to scan by: the maximum is one paper's best day, the median the literature's. */
  selectivity_median: number | null;
  selectivity_max: number | null;
  n_selectivity_censored: number | null;
  /** Always read together: only 25 campaigns state calls at all. */
  n_call_campaigns: number | null;
  n_active_campaigns: number | null;
}

export interface HitPage {
  total: number;
  items: HitProfile[];
  population: {
    compounds: number;
    beyond_potency: number;
    potency_only: number;
    elsewhere_only: number;
    whole_cell_and_nothing_else: number;
    with_selectivity: number;
    /** Drawable from `compound_structures`; null when the store predates that table. */
    with_structure: number | null;
    n_cytotox: number;
    n_adme: number;
    n_in_vivo: number;
  };
}

export interface CompoundEvidence extends ScreenResult {
  screen_title: string | null;
  description: string | null;
  strain: string | null;
  assay_condition: string | null;
  year: number | null;
  document_chembl_id: string | null;
  pubmed_id: string | null;
}

export type ConceptKind = "pfam" | "go" | "pathway" | "condition";

/** Every gene sharing one annotation, or called in one conditional TnSeq screen. */
export interface Concept {
  kind: ConceptKind;
  id: string;
  label: string | null;
  basis: string;
  genes: { rv_id: string; gene_name: string | null; product: string | null; log2fc: number | null }[];
}

export const api = {
  meta: () => get<Meta>("/meta"),
  screens: (query: Record<string, unknown> = {}) => get<ScreenPage>("/screens", { limit: 1000, ...query }),
  screen: (id: string) => get<ScreenDetail>(`/screens/${encodeURIComponent(id)}`),
  screenResults: (id: string, query: Record<string, unknown> = {}) =>
    get<Page<ScreenResult> & { n_with_structure: number | null }>(
      `/screens/${encodeURIComponent(id)}/results`,
      { limit: 60, ...query },
    ),
  hits: (query: Record<string, unknown> = {}) => get<HitPage>("/hits", { limit: 300, ...query }),
  compoundEvidence: (id: string, query: Record<string, unknown> = {}) =>
    get<Page<CompoundEvidence>>(`/compounds/${encodeURIComponent(id)}/screen-evidence`, { limit: 100, ...query }),
  targets: (query: TargetQuery) =>
    get<{ total: number; limit: number; offset: number; items: TargetSummary[] }>(
      "/targets",
      query as Record<string, unknown>,
    ),
  target: (rvId: string) => get<TargetDetail>(`/targets/${rvId}`),
  concept: (kind: ConceptKind, id: string) => get<Concept>(`/concepts/${kind}`, { id }),
  proteinAssays: (rvId: string) => get<ProteinAssay[]>(`/targets/${encodeURIComponent(rvId)}/protein-assays`),
  compound: (id: string) => get<CompoundDetail>(`/compounds/${id}`),
  drugs: () => get<Page<DrugSummary>>("/drugs", { limit: 1000 }),
  drug: (id: string) => get<DrugDetail>(`/drugs/${id}`),
  trials: () => get<Page<Trial>>("/trials", { limit: 2000 }),
  trial: (nctId: string) => get<TrialDetail>(`/trials/${nctId}`),
  search: (q: string) => get<SearchResults>("/search", { q, limit: 6 }),
};
