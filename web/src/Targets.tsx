/**
 * Targets: the genome read as a target landscape rather than a list of loci.
 *
 * Two things live here that the genome view does not provide. The first is
 * `validation_status`, the furthest point of chemical interrogation on record
 * for each protein. The second is a cohort built by intersecting stated
 * criteria, each of which resolves to yes, no or no record, with the count of
 * every state shown so that an absent record is never silently read as a
 * negative one.
 *
 * Nothing here is ranked, weighted or combined into a score. The criteria are
 * the reader's to choose and the counts are set sizes.
 */
import { useMemo, useState } from "react";
import { FilterRail } from "./FilterRail";

import type { TargetSummary, ValidationStatus } from "./api";

const STATUS_ORDER: ValidationStatus[] = [
  "clinically_validated",
  "clinical_stage",
  "biochemically_interrogated",
  "annotated_target",
  "screened",
  "genetically_nominated",
  "not_interrogated",
];

const STATUS_LABEL: Record<ValidationStatus, string> = {
  clinically_validated: "Clinically validated",
  clinical_stage: "Clinical-stage chemical matter",
  biochemically_interrogated: "Biochemically interrogated",
  annotated_target: "Annotated target, no assay",
  screened: "Screened, no protein assay",
  genetically_nominated: "Genetically nominated",
  not_interrogated: "Not interrogated",
};

const STATUS_BASIS: Record<ValidationStatus, string> = {
  clinically_validated: "An approved drug is recorded against this protein.",
  clinical_stage: "A compound in clinical development is recorded against this protein.",
  biochemically_interrogated: "A ChEMBL assay is recorded against this protein as a single-protein target.",
  annotated_target: "A ChEMBL target exists for this protein, with no assay recorded against it.",
  screened: "A screening campaign reaches this protein, with no assay recorded against it.",
  genetically_nominated: "Essential or confidently vulnerable, with no chemical record.",
  not_interrogated: "No chemical or genetic record in these sources reaches this locus.",
};

type Verdict = "y" | "n" | "r";

interface Criterion {
  id: string;
  label: string;
  column: string;
  verdict: (row: TargetSummary) => Verdict;
}

/**
 * Each criterion names the column it reads and the condition under which that
 * column carries no record. The no-record state is never folded into "no":
 * for several of these columns it is the majority of the genome.
 */
const CRITERIA: Criterion[] = [
  {
    id: "essential",
    label: "Essential (ES or ESD)",
    column: "essentiality",
    verdict: r => (r.essentiality == null ? "r" : r.essentiality_essential ? "y" : "n"),
  },
  {
    id: "vulnerable",
    label: "Vulnerability confidently measured",
    column: "vulnerability_index, vulnerability_certain",
    verdict: r => (r.vulnerability_index == null ? "r" : r.vulnerability_certain ? "y" : "n"),
  },
  {
    id: "strain",
    label: "Strain difference reported (HN878)",
    column: "hn878_delta_vi",
    verdict: r => (r.hn878_delta_vi == null ? "r" : "y"),
  },
  {
    id: "cholesterol",
    label: "Assessable on cholesterol",
    column: "cholesterol_measured",
    verdict: r => (r.cholesterol_measured == null ? "r" : r.cholesterol_measured ? "y" : "n"),
  },
  {
    id: "structure",
    label: "Structure of this protein",
    column: "has_structure",
    verdict: r => (r.has_structure ? "y" : "n"),
  },
  {
    id: "orthologue",
    label: "Structure of a mycobacterial orthologue",
    column: "n_orthologue_pdb",
    verdict: r => (r.n_orthologue_pdb > 0 ? "y" : "n"),
  },
  {
    id: "human",
    label: "No human homologue at 30% identity",
    column: "close_human_homolog",
    verdict: r => (r.close_human_homolog ? "n" : "y"),
  },
  {
    id: "paralog",
    label: "No paralogue at 30% over 70%",
    column: "close_paralog",
    verdict: r => (r.close_paralog ? "n" : "y"),
  },
  {
    id: "assay",
    label: "Assay against the purified protein",
    column: "n_protein_assays",
    verdict: r => (r.n_protein_assays > 0 ? "y" : "n"),
  },
  {
    id: "chembl",
    label: "ChEMBL target of its own",
    column: "n_chembl_targets",
    verdict: r => (r.n_chembl_targets > 0 ? "y" : "n"),
  },
  {
    id: "precedent",
    label: "Approved drug against its Pfam domain",
    column: "n_precedent_approved",
    verdict: r => (r.n_precedent_approved == null ? "r" : r.n_precedent_approved > 0 ? "y" : "n"),
  },
  {
    id: "who",
    label: "In the WHO mutation catalogue",
    column: "in_who_catalogue",
    verdict: r => (r.in_who_catalogue ? "y" : "n"),
  },
];

const VERDICTS: [Verdict, string][] = [["y", "yes"], ["n", "no"], ["r", "no record"]];

const n0 = (v: number | null | undefined) => (v == null ? null : v.toLocaleString());
const f1 = (v: number | null | undefined) => (v == null ? null : v.toFixed(1));
const f2 = (v: number | null | undefined) => (v == null ? null : v.toFixed(2));
const pct = (v: number | null | undefined) => (v == null ? null : `${Math.round(v * 100)}%`);

/** A value the store does not carry reads as no record, never as zero. */
function Row({ label, column, value }: { label: string; column: string; value: string | null }) {
  return (
    <>
      <div className="k">
        {label}
        <code>{column}</code>
      </div>
      <div className={value == null ? "v none" : "v"}>{value ?? "no record"}</div>
    </>
  );
}

function Dimension({ title, basis, children }: { title: string; basis: string; children: React.ReactNode }) {
  return (
    <section className="assess-dim">
      <h4>{title}</h4>
      <p className="assess-basis">{basis}</p>
      <div className="assess-kv">{children}</div>
    </section>
  );
}

function Profile({ row, onOpenGene }: { row: TargetSummary; onOpenGene: (rv: string) => void }) {
  const status = row.validation_status;
  return (
    <div className="assess-profile">
      <div className="assess-profile-head">
        <div>
          <h3>{row.gene_name ?? row.rv_id}</h3>
          <p className="assess-product">{row.product}</p>
        </div>
        <button type="button" className="rowbtn" onClick={() => onOpenGene(row.rv_id)}>
          Full record
        </button>
      </div>
      {status ? (
        <p className="assess-status-line">
          <span className="chip accent">{STATUS_LABEL[status]}</span>
          <span>{STATUS_BASIS[status]}</span>
        </p>
      ) : (
        <p className="assess-basis">
          Validation status is unavailable: the clinical or screening layer is not built in this store.
        </p>
      )}
      {row.shared_accession && (
        <p className="assess-caveat">
          This locus shares a UniProt accession with at least one other. Evidence keyed on the
          accession — structures, ligands and homology — cannot be attributed to one locus alone.
        </p>
      )}

      <Dimension
        title="Genetic validation"
        basis="Transposon-insertion essentiality (DeJesus 2017) and CRISPRi vulnerability (Bosch 2021). Essentiality asks whether the locus tolerates disruption; the vulnerability index asks how far expression must fall before fitness is impaired. Essential means ES or ESD; growth-defect loci carry a fitness cost without being essential. The index is negative, and a positive HN878 difference indicates reduced vulnerability in the clinical isolate."
      >
        <Row label="Essentiality call" column="essentiality" value={row.essentiality_label ?? row.essentiality} />
        <Row
          label="Disruption carries a fitness cost"
          column="essentiality_fitness_cost"
          value={row.essentiality_fitness_cost ? "yes" : "no"}
        />
        <Row label="Vulnerability index, H37Rv" column="vulnerability_index" value={f2(row.vulnerability_index)} />
        <Row
          label="Reported as confident"
          column="vulnerability_certain"
          value={row.vulnerability_index == null ? null : row.vulnerability_certain ? "yes" : "no"}
        />
        <Row label="Vulnerability index, HN878" column="hn878_vulnerability_index" value={f2(row.hn878_vulnerability_index)} />
        <Row
          label="HN878 minus H37Rv"
          column="hn878_delta_vi"
          value={row.hn878_delta_vi == null ? null : `${row.hn878_delta_vi > 0 ? "+" : ""}${row.hn878_delta_vi.toFixed(2)}`}
        />
      </Dimension>

      <Dimension
        title="Conditional essentiality"
        basis="Fitness with cholesterol as the sole carbon source (Griffin 2011). Transposon screens cannot assess loci that take no insertions; those loci are reported as unmeasured rather than unaffected."
      >
        <Row
          label="Assessable in the screen"
          column="cholesterol_measured"
          value={row.cholesterol_measured == null ? null : row.cholesterol_measured ? "yes" : "no insertions"}
        />
        <Row
          label="Required on cholesterol"
          column="cholesterol_required"
          value={row.cholesterol_required == null ? null : row.cholesterol_required ? "yes" : "no"}
        />
        <Row label="log2 ratio" column="cholesterol_log2_ratio" value={f2(row.cholesterol_log2_ratio)} />
        <Row
          label="Distinct whole-cell conditions"
          column="whole_cell_conditions"
          value={row.whole_cell_conditions.length ? String(row.whole_cell_conditions.length) : null}
        />
      </Dimension>

      <Dimension
        title="Target engagement"
        basis="ChEMBL assays recorded against this protein as a single-protein target; assays filed against complexes containing it are reported separately. Resistance variants are those graded as associated with resistance in the WHO mutation catalogue, 2nd edition."
      >
        <Row label="Evidence class" column="chembl_evidence" value={row.chembl_evidence} />
        <Row label="Assays against the purified protein" column="n_protein_assays" value={n0(row.n_protein_assays)} />
        <Row label="Largest single assay, compounds" column="max_assay_compounds" value={n0(row.max_assay_compounds)} />
        <Row label="Assays against complexes" column="n_complex_assays" value={n0(row.n_complex_assays)} />
        <Row label="In the WHO catalogue" column="in_who_catalogue" value={row.in_who_catalogue ? "yes" : "no"} />
        <Row label="Variants graded associated" column="n_variants_associated" value={n0(row.n_variants_associated)} />
      </Dimension>

      <Dimension
        title="Structural tractability"
        basis="Experimental structures deposited under this protein's own accession, and structures of mycobacterial orthologues reported with sequence identity and coverage. Orthologue residue numbering follows the orthologue, not this protein."
      >
        <Row label="Structures of this protein" column="n_pdb" value={n0(row.n_pdb)} />
        <Row label="Best resolution" column="best_resolution" value={row.best_resolution == null ? null : `${row.best_resolution.toFixed(2)} Å`} />
        <Row label="With a bound ligand" column="n_pdb_with_ligand" value={n0(row.n_pdb_with_ligand)} />
        <Row
          label="Identical sequence under another accession"
          column="same_sequence_structure"
          value={row.same_sequence_structure ? "yes" : "no"}
        />
        <Row label="Orthologue structures" column="n_orthologue_pdb" value={n0(row.n_orthologue_pdb)} />
        <Row
          label="Nearest solved orthologue"
          column="closest_orthologue_gene"
          value={row.closest_orthologue_gene ? `${row.closest_orthologue_gene} · ${row.closest_orthologue_organism ?? "organism not stated"}` : null}
        />
        <Row
          label="Its identity and coverage"
          column="closest_orthologue_identity, closest_orthologue_coverage"
          value={row.closest_orthologue_identity == null ? null : `${pct(row.closest_orthologue_identity)} over ${pct(row.closest_orthologue_coverage) ?? "?"}`}
        />
        <Row
          label="Predicted model"
          column="has_predicted, plddt_mean"
          value={row.has_predicted ? `AlphaFold, mean pLDDT ${f1(row.plddt_mean) ?? "not stated"}` : "none"}
        />
      </Dimension>

      <Dimension
        title="Chemical matter"
        basis="Protein-level potency as pChEMBL; whole-cell potency as pMIC, the negative log of the MIC in mol/L. MICs censored at the highest concentration tested are counted but not converted. Screening campaign sizes are the deposited compound sets."
      >
        <Row label="Compounds with protein-level potency" column="n_compounds" value={n0(row.n_compounds)} />
        <Row label="Best pChEMBL" column="best_pchembl" value={f2(row.best_pchembl)} />
        <Row label="Whole-cell measurements" column="n_whole_cell" value={n0(row.n_whole_cell)} />
        <Row label="Best pMIC" column="best_pmic" value={f2(row.best_pmic)} />
        <Row
          label="MICs, of which censored"
          column="n_mic, n_mic_censored"
          value={`${n0(row.n_mic)} of which ${n0(row.n_mic_censored)}`}
        />
        <Row label="Campaigns on this protein" column="n_target_screens" value={n0(row.n_target_screens)} />
        <Row label="Largest campaign, compounds" column="max_screen_compounds" value={n0(row.max_screen_compounds)} />
        <Row label="Compounds called active" column="n_screen_actives" value={n0(row.n_screen_actives)} />
      </Dimension>

      <Dimension
        title="Liabilities"
        basis="Human homologues from phmmer against the reviewed human proteome; paralogues from phmmer against the Mtb proteome, called at 30% identity over 70% of the query length. Drug precedent counts approved drugs recorded against other single-protein targets that share a Pfam domain with this protein; a shared domain is not a shared binding site."
      >
        <Row
          label="Closest human homologue"
          column="human_homolog_gene, human_homolog_identity"
          value={row.human_homolog_gene ? `${row.human_homolog_gene} · ${pct(row.human_homolog_identity)}` : row.human_homolog ? "unnamed" : "none above threshold"}
        />
        <Row
          label="Closest paralogue meeting both thresholds"
          column="closest_paralog_gene, closest_paralog_identity"
          value={row.closest_paralog_gene ? `${row.closest_paralog_gene} · ${pct(row.closest_paralog_identity)}` : "none"}
        />
        <Row
          label="Nearest relative, any coverage"
          column="nearest_relative_gene"
          value={row.nearest_relative_gene ? `${row.nearest_relative_gene} · ${pct(row.nearest_relative_identity)}` : null}
        />
        <Row label="Approved drugs against the domain" column="n_precedent_approved" value={n0(row.n_precedent_approved)} />
        <Row label="Of those, acting on a human protein" column="n_precedent_human_target" value={n0(row.n_precedent_human_target)} />
        <Row label="Filed against a complex, not counted" column="n_precedent_complex" value={n0(row.n_precedent_complex)} />
        <Row label="Domain carrying the precedent" column="precedent_pfam_name" value={row.precedent_pfam_name} />
      </Dimension>

      {row.drug_names && row.drug_names.length > 0 && (
        <Dimension
          title="Drugs recorded against this protein"
          basis="A drug reaches a gene through a ChEMBL single-protein mechanism or an annotation matched to a ChEMBL synonym. Membership of a complex a drug is filed against is not such a record, and resistance to a drug is not engagement with it."
        >
          <Row label="Drugs" column="drug_names" value={row.drug_names.join(", ")} />
          <Row
            label="Highest phase for a TB indication"
            column="best_drug_phase"
            value={row.best_drug_phase == null ? null : `phase ${row.best_drug_phase}`}
          />
          <Row label="Interventional trials" column="n_trials" value={n0(row.n_trials)} />
        </Dimension>
      )}
    </div>
  );
}

export function Targets({
  all,
  onOpenGene,
}: {
  all: TargetSummary[];
  onOpenGene: (rvId: string) => void;
}) {
  const [picks, setPicks] = useState<Record<string, Verdict>>({});
  const [status, setStatus] = useState<ValidationStatus | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  // The genome's coding loci. RNA genes carry no protein to interrogate, so a
  // target landscape that counted them would report a denominator it cannot
  // assess.
  const genes = useMemo(() => all.filter(r => r.feature === "CDS"), [all]);

  const verdicts = useMemo(() => {
    const table = new Map<string, Verdict[]>();
    for (const row of genes) table.set(row.rv_id, CRITERIA.map(c => c.verdict(row)));
    return table;
  }, [genes]);

  const passes = useMemo(
    () => (row: TargetSummary, skip?: string) => {
      const v = verdicts.get(row.rv_id);
      if (!v) return false;
      return CRITERIA.every((c, i) => {
        if (c.id === skip) return true;
        const want = picks[c.id];
        return !want || v[i] === want;
      });
    },
    [verdicts, picks],
  );

  const cohort = useMemo(
    () => genes.filter(r => (status == null || r.validation_status === status) && passes(r)),
    [genes, status, passes],
  );

  // Status counts ignore the status filter itself, so the distribution stays
  // readable while one level is open.
  const statusCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const row of genes) {
      if (!passes(row)) continue;
      const key = row.validation_status ?? "unknown";
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return counts;
  }, [genes, passes]);

  const widest = Math.max(1, ...STATUS_ORDER.map(s => statusCounts.get(s) ?? 0));

  // Each criterion's counts are taken over the cohort filtered by the others,
  // so the three numbers always sum to a set the reader can act on.
  const criterionCounts = useMemo(
    () =>
      CRITERIA.map((c, i) => {
        const tally: Record<Verdict, number> = { y: 0, n: 0, r: 0 };
        for (const row of genes) {
          if (status != null && row.validation_status !== status) continue;
          if (!passes(row, c.id)) continue;
          const v = verdicts.get(row.rv_id);
          if (v) tally[v[i]] += 1;
        }
        return tally;
      }),
    [genes, status, passes, verdicts],
  );

  // The cohort step by step: what each criterion costs, in the order shown.
  const steps = useMemo(() => {
    const active = CRITERIA.map((c, i) => ({ c, i })).filter(x => picks[x.c.id]);
    const out: { label: string; count: number; drop: number }[] = [];
    let running = genes.filter(r => status == null || r.validation_status === status);
    if (status != null) {
      out.push({ label: STATUS_LABEL[status], count: running.length, drop: genes.length - running.length });
    }
    for (const { c } of active) {
      const want = picks[c.id];
      const before = running.length;
      running = running.filter(r => {
        const v = verdicts.get(r.rv_id);
        return v ? v[CRITERIA.indexOf(c)] === want : false;
      });
      const suffix = want === "y" ? "" : want === "n" ? " — no" : " — no record";
      out.push({ label: c.label + suffix, count: running.length, drop: before - running.length });
    }
    return out;
  }, [genes, status, picks, verdicts]);

  const chosen = selected ? (genes.find(r => r.rv_id === selected) ?? null) : null;
  const active = Object.keys(picks).length > 0 || status != null;

  return (
    <div className={`body targets-body${chosen ? " detail-open" : ""}`}>
      <FilterRail label="Criteria">
        <div className="group">
          <div className="assess-rail-head">
            <p className="lab">Criteria</p>
            {active && (
              <button
                type="button"
                className="clear-filters"
                onClick={() => {
                  setPicks({});
                  setStatus(null);
                }}
              >
                Clear
              </button>
            )}
          </div>
          <p className="assess-basis">
            Each criterion resolves to yes, no, or no record. Absence of a record is reported
            separately from a negative result.
          </p>
          {CRITERIA.map((c, i) => (
            <div className="assess-crit" key={c.id}>
              <span className="assess-crit-label">{c.label}</span>
              <code>{c.column}</code>
              <div className="assess-seg">
                {VERDICTS.map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    aria-pressed={picks[c.id] === key}
                    onClick={() =>
                      setPicks(prev => {
                        const next = { ...prev };
                        if (next[c.id] === key) delete next[c.id];
                        else next[c.id] = key;
                        return next;
                      })
                    }
                  >
                    <span>{label}</span>
                    <span className="c">{criterionCounts[i][key].toLocaleString()}</span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      </FilterRail>

      <main className="col canvascol targets-main">
        <section className="assess-panel">
          <div className="assess-panel-head">
            <p className="lab">Chemical validation status</p>
            <span className="assess-note">furthest record present</span>
          </div>
          <div className="assess-stages">
            {STATUS_ORDER.map(key => {
              const value = statusCounts.get(key) ?? 0;
              return (
                <button
                  key={key}
                  type="button"
                  className="assess-stage"
                  aria-pressed={status === key}
                  title={STATUS_BASIS[key]}
                  onClick={() => {
                    setStatus(status === key ? null : key);
                    setSelected(null);
                  }}
                >
                  <span className="assess-stage-name">{STATUS_LABEL[key]}</span>
                  <span className="assess-bar" style={{ width: `${(value / widest) * 100}%` }} />
                  <span className="assess-stage-n">{value.toLocaleString()}</span>
                </button>
              );
            })}
          </div>
          <p className="assess-caveat">
            Status reflects the most advanced record present and does not imply that earlier stages
            were completed. MmpL3 holds clinical-stage chemical matter with no recorded assay
            against the purified protein; its ligands reach it through the <i>M. smegmatis</i>{" "}
            orthologue.
          </p>
        </section>

        <section className="assess-panel">
          <div className="assess-panel-head">
            <p className="lab">Cohort</p>
            <span className="assess-note">
              {cohort.length.toLocaleString()} of {genes.length.toLocaleString()} coding loci
            </span>
          </div>
          <div className="assess-funnel">
            <div className="assess-step base">
              <span className="assess-step-n">{genes.length.toLocaleString()}</span>
              <span className="assess-step-l">H37Rv coding loci</span>
              <span className="assess-step-d" />
            </div>
            {steps.map(step => (
              <div className="assess-step" key={step.label}>
                <span className="assess-step-n">{step.count.toLocaleString()}</span>
                <span className="assess-step-l">{step.label}</span>
                <span className="assess-step-d">−{step.drop.toLocaleString()}</span>
              </div>
            ))}
            {!steps.length && (
              <p className="assess-basis">
                No criterion applied. Choose states in the rail to define a cohort; each step shows
                the loci it excludes.
              </p>
            )}
          </div>
        </section>

        <section className="assess-panel">
          <div className="assess-panel-head">
            <p className="lab">Loci</p>
            <span className="assess-note">
              {cohort.length > 200 ? `first 200 of ${cohort.length.toLocaleString()}` : `${cohort.length} shown`}
            </span>
          </div>
          <div className="detail-table-scroll">
            <table className="clinical-table workspace-table">
              <thead>
                <tr>
                  <th>Locus</th>
                  <th>Gene</th>
                  <th>Status</th>
                  <th>Essentiality</th>
                  <th className="num">VI</th>
                  <th className="num">PDB</th>
                  <th className="num">Assays</th>
                  <th className="num">Compounds</th>
                </tr>
              </thead>
              <tbody>
                {cohort.slice(0, 200).map(row => (
                  <tr
                    key={row.rv_id}
                    aria-selected={selected === row.rv_id}
                    onClick={() => setSelected(row.rv_id)}
                  >
                    <td>{row.rv_id}</td>
                    <td className="gene-name">{row.gene_name ?? "—"}</td>
                    <td>{row.validation_status ? STATUS_LABEL[row.validation_status] : "—"}</td>
                    <td>{row.essentiality ?? "—"}</td>
                    <td className="num">{f2(row.vulnerability_index) ?? "—"}</td>
                    <td className="num">{row.n_pdb.toLocaleString()}</td>
                    <td className="num">{row.n_protein_assays.toLocaleString()}</td>
                    <td className="num">{row.n_compounds.toLocaleString()}</td>
                  </tr>
                ))}
                {!cohort.length && (
                  <tr>
                    <td colSpan={8} className="assess-basis">
                      No locus carries every state asked for. The cohort is empty.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </main>

      {chosen && (
        <aside className="col detailcol assess-side">
          <div className="assess-panel">
            <div className="assess-panel-head">
              <p className="lab">Target profile</p>
              <button type="button" className="rowbtn" onClick={() => setSelected(null)}>
                Close
              </button>
            </div>
            <Profile row={chosen} onOpenGene={onOpenGene} />
          </div>
        </aside>
      )}
    </div>
  );
}
