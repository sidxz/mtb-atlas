/**
 * Everything the atlas knows about one gene, including what it does not know.
 *
 * Every number carries the source it came from. Absences are rendered as
 * statements ("not in the WHO catalogue, which covers 65 genes") rather than
 * as blank cells, because "essential, has a structure, no ligands" is a result
 * this app exists to produce and a zero has to be trustworthy.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import {
  conditionLabel,
  type Activity,
  type Compound,
  type ConditionHit,
  type TargetDetail as Detail,
  type Meta,
  type Variant,
} from "./api";
import { ClinicalTab, phaseLabel, type Focus } from "./Clinical";
import { StructureViewer, alphafoldSource, pdbSource, type ViewerSource } from "./StructureViewer";
import { ChemblLink, Structure } from "./Structure";
import { ProteinAssays } from "./ProteinAssays";
import { Genome } from "./Genome";
import { MaximizeButton } from "./Screens";

const SOURCES = {
  essentiality: "DeJesus 2017, mBio · Table S3 · CC BY 4.0",
  pdb: "RCSB PDB · CC0 1.0",
  alphafold: "AlphaFold DB v6 · CC BY 4.0",
  chembl: "ChEMBL 37 · CC BY-SA 3.0",
  who: "WHO catalogue 2nd ed. 2023 · ODC-By 1.0",
  vulnerability: "Bosch et al. 2021, Cell · Table S3 · CC BY 4.0",
  string: "STRING v12.5 · CC BY 4.0",
  homology: "phmmer vs reviewed human proteome (UniProt) · CC BY 4.0",
  paralogs: "phmmer vs the Mtb proteome itself (UniProt) · CC BY 4.0",
  orthologueStructures:
    "phmmer vs Mycobacteriaceae with a PDB entry (UniProt · CC BY 4.0) · RCSB PDB · CC0 1.0",
  precedent: "ChEMBL 37 mechanisms by Pfam domain (UniProt · CC BY 4.0) · CC BY-SA 3.0",
  identity: "Mycobrowser release 5 (licence not stated) · UniProt · CC BY 4.0",
  clinical: "ChEMBL TB indications and mechanisms · Bosch 2021 · ClinicalTrials.gov",
  uniprot: "UniProt · CC BY 4.0",
  cholesterol: "Griffin et al. 2011, PLoS Pathog · Tables S3/S4 · CC BY 4.0",
  tnseq: "MtbTnDB · Jinich et al. 2025, Mol Microbiol · Zenodo 10.5281/zenodo.15284946 · CC BY 4.0",
};

type Tab = "evidence" | "locus" | "structure" | "assays" | "chemistry" | "resistance" | "clinical" | "network";

const number = (value: number | null | undefined, digits = 2) =>
  value === null || value === undefined ? "—" : value.toFixed(digits);

function Row({ label, source, children }: { label: string; source?: string; children: React.ReactNode }) {
  return (
    <div className="ev">
      <span className="k">{label}</span>
      <div>{children}</div>
      {source && <span className="src">{source}</span>}
    </div>
  );
}

/**
 * Conditional TnSeq, with the three things that make it readable honestly.
 *
 * The denominator is shown, so two hits can be read against what was testable.
 * A gene that took no insertions anywhere gets the absence, not a zero. And
 * knockout backgrounds are kept apart from conditions, because a hit in one is
 * an interaction with that gene -- mmpL3 looks like it has a glycerol
 * phenotype until you notice the screen is marP_KO.
 */
function ConditionTable({ hits, interaction }: { hits: ConditionHit[]; interaction?: boolean }) {
  return (
    <div className="scroller">
      <table className="cond-table">
        <thead>
          <tr>
            <th>{interaction ? "Background" : "Condition"}</th>
            <th>Where</th>
            <th className="n">log2FC</th>
            <th className="n">q</th>
          </tr>
        </thead>
        <tbody>
          {hits.map((hit) => (
            <tr key={hit.screen_id} title={hit.description ?? hit.screen_id}>
              <td>
                {interaction ? `Δ${hit.interaction ?? "?"}` : conditionLabel(hit)}
                {/* Two doses of the same drug, or two timepoints, land on the
                    same label. The screen id is the only thing that tells them
                    apart, so it is shown rather than letting the rows read as
                    duplicates. */}
                {hits.filter((other) => conditionLabel(other) === conditionLabel(hit)).length > 1 && (
                  <span className="dim"> · {hit.screen_id.split("_vs_")[0]}</span>
                )}
                {hit.cross_study && (
                  <span className="chip warn" title="The control library is from another study, so a batch effect is possible">
                    cross-study
                  </span>
                )}
              </td>
              <td className="dim">{hit.condition_class?.replace("_", " ") ?? "—"}</td>
              <td className="n" style={{ color: hit.log2fc < 0 ? "var(--accent)" : "var(--fg)" }}>
                {hit.log2fc > 0 ? "+" : ""}
                {hit.log2fc.toFixed(2)}
              </td>
              <td className="n dim">{hit.q_value === 0 ? "<1e-5" : hit.q_value.toExponential(1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Conditions({ detail }: { detail: Detail }) {
  const { measured, unmeasured } = detail.tnseq_coverage;
  const total = measured + unmeasured;
  if (!total) {
    return <span className="absent">No annotated screen includes this gene</span>;
  }
  if (!measured) {
    return (
      <>
        <span className="absent">not measurable in any of the {unmeasured} screens</span>
        <div className="note">
          No transposon insertions were available to estimate fitness in these screens. The effect of each condition is unmeasured.
        </div>
      </>
    );
  }
  return (
    <>
      <span className="big" style={{ color: detail.conditions.length ? "var(--accent)" : "var(--fg)" }}>
        {detail.conditions.length}
      </span>{" "}
      <span className="dim">
        condition{detail.conditions.length === 1 ? "" : "s"} with significant effects ({measured} measured)
        {unmeasured > 0 && ` · ${unmeasured} unmeasured`}
      </span>
      {detail.conditions.length > 0 ? (
        <>
          <ConditionTable hits={detail.conditions} />
          <div className="note">
            Negative log2FC indicates depletion. The atlas uses q &lt; 0.05 as its significance threshold. TRANSIT counts TA sites across the whole ORF; in essential genes, surviving insertions near the ends may affect the estimate. Interpret these results alongside the essentiality classification.
          </div>
        </>
      ) : (
        <div className="note">
          No measured condition met the atlas’s significance threshold of q &lt; 0.05.
          {unmeasured > 0 &&
            " Screens without transposon insertions could not estimate an effect."}
        </div>
      )}
      {detail.interactions.length > 0 && (
        <>
          <div className="note" style={{ color: "var(--fg)" }}>
            Also significant in {detail.interactions.length} knockout background
            {detail.interactions.length === 1 ? "" : "s"}. These results describe genetic interactions with the deleted genes.
          </div>
          <ConditionTable hits={detail.interactions} interaction />
        </>
      )}
    </>
  );
}

export function TargetDetailPanel({
  detail,
  meta,
  onOpen,
  onOpenScreen,
  onClose,
  maximized,
  onMaximize,
}: {
  detail: Detail;
  meta: Meta | null;
  onOpen: (focus: Focus) => void;
  onOpenScreen?: (id: string) => void;
  onClose: () => void;
  maximized: boolean;
  onMaximize: () => void;
}) {
  const [tab, setTab] = useState<Tab>("evidence");
  // By id, not position: a ligand can sit in any of inhA's 135 entries, and
  // only the first eight have a button.
  const [structureId, setStructureId] = useState<string | null>(null);
  const [focusLigand, setFocusLigand] = useState<string | null>(null);
  const stage = useRef<HTMLDivElement | null>(null);
  const [showLigands, setShowLigands] = useState(true);
  const [showResistance, setShowResistance] = useState(true);
  const [focusResidue, setFocusResidue] = useState<number | null>(null);

  useEffect(() => {
    setStructureId(null);
    setFocusLigand(null);
    setFocusResidue(null);
  }, [detail.rv_id]);

  const sources: ViewerSource[] = useMemo(() => {
    const list = detail.structures.map((s) => pdbSource(s.pdb_id, s.title));
    if (detail.alphafold?.cif_url && detail.alphafold.entry_id) {
      list.push(alphafoldSource(detail.alphafold.cif_url, detail.alphafold.entry_id));
    }
    return list;
  }, [detail]);

  const current = sources.find((s) => s.id === structureId) ?? sources[0];
  const buttons = sources.slice(0, 8);
  if (current && !buttons.includes(current)) buttons.push(current);
  const viewLigand = (pdbId: string, comp: string) => {
    setStructureId(pdbId);
    setFocusLigand(comp);
    setFocusResidue(null);
    setShowLigands(true);
    stage.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };

  const mappable = detail.variants.filter((v) => v.residue_position !== null);

  return (
    <>
      <div className="detailhead gene-detail-head">
        <div className="gene-detail-title">
          <div className="row">
            <span className="rv">{detail.rv_id}</span>
            {detail.gene_name && detail.gene_name !== detail.rv_id && (
              <span className="gn">{detail.gene_name}</span>
            )}
            {detail.conflict && <span className="chip warn">{detail.acc_status?.replace(/_/g, " ")}</span>}
            {detail.is_pseudogene && <span className="chip warn">pseudogene</span>}
          </div>
          <div className="detail-head-actions">
            <MaximizeButton expanded={maximized} onToggle={onMaximize} label="gene detail" />
            <Link className="rowbtn detail-map-link" to={`/map/${encodeURIComponent(detail.rv_id)}`}>Open in map</Link>
            <button className="closedetail" type="button" title="Close and widen the gene table (Esc)" aria-label="Close gene detail" onClick={onClose}>×</button>
          </div>
        </div>
        <p>{detail.product}</p>
      </div>

      <div className="tabs">
        {(
          [
            ["evidence", "Evidence", null],
            ["locus", "Locus", null],
            ["structure", "Structure", detail.n_pdb + (detail.has_predicted ? 1 : 0)],
            ["chemistry", "Chemistry", detail.n_compounds],
            ["assays", "Protein assays", detail.n_protein_assays],
            ["resistance", "Resistance", detail.n_variants_associated],
            ["clinical", "Clinical", detail.n_drugs],
            ["network", "Network", detail.n_partners],
          ] as [Tab, string, number | null][]
        ).map(([key, label, badge]) => (
          <button key={key} type="button" aria-pressed={tab === key} onClick={() => setTab(key)}>
            {label}
            {badge !== null && badge > 0 && <span className="badge">{badge}</span>}
          </button>
        ))}
      </div>

      {/* Only the evidence tab columnises: its rows are independent blocks.
          The others hold one table or one viewer, which want the full width. */}
      <div className={tab === "evidence" ? "panel evidence" : "panel"}>
        {tab === "evidence" && <Evidence detail={detail} />}
        {tab === "locus" && <Genome rvId={detail.rv_id} />}
        {tab === "assays" && <ProteinAssays key={detail.rv_id} rvId={detail.rv_id} />}

        {tab === "structure" && (
          <>
            {sources.length === 0 ? (
              <>
                <p className="absent">
                  No experimental structure and no AlphaFold model for this accession.
                </p>
                <OrthologueStructureTable detail={detail} />
              </>
            ) : (
              <>
                <div className="viewerbar">
                  {buttons.map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      className="minibtn"
                      aria-pressed={s === current}
                      onClick={() => {
                        setStructureId(s.id);
                        setFocusLigand(null);
                      }}
                    >
                      {s.id}
                    </button>
                  ))}
                </div>
                <div ref={stage}>
                  <StructureViewer
                    source={current ?? null}
                    variants={detail.variants}
                    showLigands={showLigands}
                    showResistance={showResistance}
                    focusResidue={focusResidue}
                    focusLigand={focusLigand}
                  />
                </div>
                <div className="viewerbar">
                  <button
                    type="button"
                    className="minibtn"
                    aria-pressed={showLigands}
                    onClick={() => setShowLigands((v) => !v)}
                  >
                    ligands
                  </button>
                  <button
                    type="button"
                    className="minibtn"
                    aria-pressed={showResistance}
                    onClick={() => setShowResistance((v) => !v)}
                  >
                    resistance residues
                  </button>
                </div>
                <div className="vkey">
                  <div>
                    <i className="sw" style={{ background: "#5b7fb5" }} />
                    {current?.predicted ? "pLDDT confidence" : "backbone"}
                  </div>
                  <div>
                    <i className="sw" style={{ background: "#2fae99" }} />
                    ligands and cofactors
                  </div>
                  {mappable.length > 0 && (
                    <div>
                      <i className="sw" style={{ background: "#e0218a" }} />
                      WHO-graded residue
                    </div>
                  )}
                </div>
                <BoundLigands
                  detail={detail}
                  viewing={{ pdbId: current?.id ?? null, comp: focusLigand }}
                  onView={viewLigand}
                  onOpen={onOpen}
                />
                <StructureTable detail={detail} />
                <OrthologueStructureTable detail={detail} />
              </>
            )}
          </>
        )}

        {tab === "chemistry" && <Chemistry detail={detail} onOpen={onOpen} onOpenScreen={onOpenScreen} />}

        {tab === "clinical" && <ClinicalTab detail={detail} meta={meta} onOpen={onOpen} />}

        {tab === "network" && <Network detail={detail} />}

        {tab === "resistance" && (
          <Resistance detail={detail} onFocus={(position) => {
            setTab("structure");
            setFocusLigand(null);
            setFocusResidue(position);
          }} />
        )}
      </div>
    </>
  );
}

function Protein({ detail }: { detail: Detail }) {
  const [open, setOpen] = useState(false);
  // Defaulted, not asserted: an older API is a degraded page, not a blank one.
  const list = <T,>(value: T[] | null | undefined): T[] => value ?? [];
  if (!detail.uniprot_acc) {
    return (
      <Row label="Protein">
        <span className="absent">No protein record is available. This may be an RNA gene or a locus without a mapped accession.</span>
      </Row>
    );
  }
  const long = (detail.function ?? "").length > 320;
  return (
    <Row
      label="Protein"
      source={`${SOURCES.uniprot} · ${
        detail.reviewed ? "reviewed entry (Swiss-Prot, curated)" : "unreviewed entry (TrEMBL, automatic)"
      } · ${detail.protein_existence ?? "existence not stated"}`}
    >
      {detail.function ? (
        <div style={{ fontSize: 12.5, lineHeight: 1.5 }}>
          {long && !open ? `${detail.function.slice(0, 320)}… ` : `${detail.function} `}
          {long && (
            <button type="button" className="minibtn" onClick={() => setOpen((v) => !v)}>
              {open ? "less" : "more"}
            </button>
          )}
        </div>
      ) : (
        <span className="absent">UniProt states no function for this entry</span>
      )}
      <div className="ids" style={{ marginTop: 6 }}>
        {list(detail.locations).map((l) => (
          <span key={l}>{l}</span>
        ))}
        <span>
          {detail.n_transmembrane
            ? `${detail.n_transmembrane} transmembrane segment${detail.n_transmembrane === 1 ? "" : "s"}`
            : "no transmembrane segment annotated"}
        </span>
        {detail.signal_peptide && <span>signal peptide</span>}
      </div>
      {list(detail.pathways).map((p) => (
        <div className="note" key={p} style={{ color: "var(--fg)" }}>
          Pathway: {p}
        </div>
      ))}
      {list(detail.reactions).slice(0, 2).map((r) => (
        <div className="note mono" key={r}>
          {r}
        </div>
      ))}
      {list(detail.cofactors).length > 0 && (
        <div className="note">Cofactor: {detail.cofactors.join(", ")}</div>
      )}
      {list(detail.go_process).length > 0 && (
        <div className="note">Process: {detail.go_process.slice(0, 6).join(" · ")}</div>
      )}
      {detail.disruption_phenotype && <p className="caveat">Disruption: {detail.disruption_phenotype}</p>}
      <div className="note">
        UniProt cites {list(detail.pubmed_ids).length} paper{list(detail.pubmed_ids).length === 1 ? "" : "s"} for this
        entry ·{" "}
        <a href={`https://www.uniprot.org/uniprotkb/${detail.uniprot_acc}/entry`} target="_blank" rel="noreferrer">
          {detail.uniprot_acc} ↗
        </a>
      </div>
    </Row>
  );
}

function Evidence({ detail }: { detail: Detail }) {
  return (
    <>
      <Protein detail={detail} />

      <Row label="Essentiality" source={SOURCES.essentiality}>
        {detail.essentiality ? (
          <>
            <span
              className="big"
              style={{ color: detail.essentiality_essential ? "var(--accent)" : "var(--fg)" }}
            >
              {detail.essentiality_label}
            </span>
            <div className="note">
              {detail.ta_sites ?? "—"} TA sites. Growth condition: {detail.essentiality_condition}.
            </div>
          </>
        ) : (
          <span className="absent">No classification recorded</span>
        )}
      </Row>

      <Row label="On cholesterol" source={SOURCES.cholesterol}>
        {detail.cholesterol_measured === null ? (
          <span className="absent">this locus was not in the screen</span>
        ) : detail.cholesterol_measured === false ? (
          <>
            <span className="absent">Not measured: no transposon insertions</span>
            <div className="note">
              No transposon insertions were available to compare fitness between carbon sources. The effect of cholesterol was not measured.
            </div>
          </>
        ) : (
          <>
            <span
              className="big"
              style={{ color: detail.cholesterol_required ? "var(--accent)" : "var(--fg)" }}
            >
              {(detail.cholesterol_log2_ratio ?? 0) > 0 ? "+" : ""}
              {number(detail.cholesterol_log2_ratio, 2)}
            </span>{" "}
            <span className="dim">
              log2 cholesterol/glycerol · p {detail.cholesterol_p?.toExponential(1) ?? "—"}
            </span>
            <div className="note">
              Negative is depleted on cholesterol, the carbon source M. tuberculosis uses
              inside a macrophage.
            </div>
            {detail.cholesterol_required && (
              <div className="note" style={{ color: "var(--fg)" }}>
                One of the 96 genes the authors call <b>specifically required on cholesterol</b>.
              </div>
            )}
          </>
        )}
        {detail.required_in_vivo && (
          <div className="note" style={{ color: "var(--fg)" }}>
            Required in a mouse infection — Sassetti &amp; Rubin 2003, carried in Griffin&rsquo;s table.
          </div>
        )}
      </Row>

      <Row label="Across conditions" source={SOURCES.tnseq}>
        <Conditions detail={detail} />
      </Row>

      <Row label="Vulnerability (CRISPRi)" source={SOURCES.vulnerability}>
        {detail.vulnerability_index === null ? (
          <span className="absent">not measured</span>
        ) : (
          <>
            <span
              className="big"
              style={{ color: detail.vulnerability_certain ? "var(--accent)" : "var(--fg-dim)" }}
            >
              {detail.vulnerability_index.toFixed(2)}
            </span>{" "}
            <span className="dim">
              {detail.vi_lower !== null && detail.vi_upper !== null
                ? `(${detail.vi_lower.toFixed(1)} to ${detail.vi_upper.toFixed(1)})`
                : ""}
            </span>
            <div className="note">
              More negative values indicate greater sensitivity to reduced gene expression. CRISPRi measures the effect of knockdown; the essentiality screen measures the effect of gene disruption.
            </div>
            {!detail.vulnerability_certain && (
              <p className="caveat">
                This estimate did not meet Bosch 2021’s confidence criteria.
              </p>
            )}
            {detail.antibacterial && (
              <div className="note" style={{ color: "var(--fg)" }}>
                Bosch 2021 drug annotation: <b>{detail.antibacterial}</b>.
              </div>
            )}
            <ClinicalStrain detail={detail} />
          </>
        )}
      </Row>

      <Row label="Human homolog" source={SOURCES.homology}>
        {detail.human_homolog ? (
          <>
            <span className="chip homology">
              {detail.human_homolog_gene ?? detail.human_homolog_acc}
            </span>{" "}
            <span className="mono">
              {Math.round((detail.human_homolog_identity ?? 0) * 100)}% identity
            </span>{" "}
            <span className="dim">
              E = {detail.human_homolog_evalue?.toExponential(1)}
            </span>
            <div className="note">
              {detail.close_human_homolog
                ? "Meets the atlas’s 30% identity threshold for a close human homolog. Selectivity requires experimental assessment."
                : "Below the atlas’s 30% identity threshold for a close human homolog."}
            </div>
          </>
        ) : (
          <>
            <span className="chip ok">none detected</span>
            <div className="note">
              No reviewed human protein matches at E ≤ 1e-5 (phmmer over the whole human
              proteome).
            </div>
          </>
        )}
      </Row>

      <Row label="Redundancy" source={SOURCES.paralogs}>
        {detail.close_paralog ? (
          <>
            <span className="chip warn">{detail.closest_paralog_gene}</span>{" "}
            <span className="mono">
              {Math.round((detail.closest_paralog_identity ?? 0) * 100)}% identity
            </span>
            {detail.n_close_paralogs > 1 && (
              <span className="dim"> · {detail.n_close_paralogs} close paralogs</span>
            )}
            <div className="note">
              A related Mtb protein meets the threshold of 30% identity over 70% of this protein. Sequence similarity alone does not establish whether it can compensate for inhibition.
            </div>
          </>
        ) : detail.has_paralog ? (
          <>
            <span className="chip ok">no close paralog</span>{" "}
            <span className="dim">
              nearest relative {detail.nearest_relative_gene} at{" "}
              <span className="mono">
                {Math.round((detail.nearest_relative_identity ?? 0) * 100)}%
              </span>{" "}
              over{" "}
              <span className="mono">
                {Math.round((detail.nearest_relative_coverage ?? 0) * 100)}%
              </span>{" "}
              of the protein
            </span>
            <div className="note">
              {detail.n_paralogs} relative{detail.n_paralogs === 1 ? "" : "s"} in the genome,
              none meeting both thresholds for a close paralog: 30% identity and 70% query coverage. Functional redundancy has not been assessed.
            </div>
          </>
        ) : (
          <>
            <span className="chip ok">none detected</span>
            <div className="note">
              No other Mtb protein matched at E ≤ 1e-5 in the phmmer search.
            </div>
          </>
        )}
      </Row>

      <Row label="Experimental structure" source={SOURCES.pdb}>
        {detail.n_pdb ? (
          <>
            <span className="big">{detail.n_pdb}</span>{" "}
            <span className="dim">
              entr{detail.n_pdb === 1 ? "y" : "ies"}
              {detail.best_resolution ? `, best ${number(detail.best_resolution)} Å` : ""}
            </span>
            <div className="ids" style={{ marginTop: 5 }}>
              {detail.structures.slice(0, 10).map((s) => (
                <span key={s.pdb_id}>{s.pdb_id}</span>
              ))}
              {detail.n_pdb > 10 && <span>+{detail.n_pdb - 10}</span>}
            </div>
          </>
        ) : (
          <span className="absent">No structure under this accession</span>
        )}
        <Borrowed detail={detail} />
      </Row>

      <Row label="Predicted structure" source={SOURCES.alphafold}>
        {detail.alphafold ? (
          <>
            <span className="mono">{detail.alphafold.entry_id}</span>
            <div className="note">
              mean pLDDT {number(detail.alphafold.plddt_mean, 1)} · model {detail.alphafold.created}
            </div>
            <PlddtBar predicted={detail.alphafold} />
          </>
        ) : (
          <span className="absent">none</span>
        )}
      </Row>

      <Row label="Chemical matter" source={SOURCES.chembl}>
        {detail.n_activities ? (
          <>
            <span className="big">{detail.n_activities.toLocaleString()}</span>{" "}
            <span className="dim">activities, {detail.n_compounds} compounds</span>
            <div className="note" style={{ color: "var(--fg)" }}>
              best pChEMBL <b className="mono">{number(detail.best_pchembl)}</b>
              {detail.best_pmic !== null && (
                <>
                  {" "}
                  · best pMIC <b className="mono">{number(detail.best_pmic)}</b>
                  <span className="dim">
                    {" "}
                    (median {number(detail.median_pmic)} over {detail.n_mic} MIC
                    {detail.n_mic === 1 ? "" : "s"})
                  </span>
                </>
              )}
              {detail.best_whole_cell_pchembl !== null && (
                <> · whole-cell pChEMBL <b className="mono">{number(detail.best_whole_cell_pchembl)}</b></>
              )}
            </div>
            {detail.n_mic_censored > 0 && (
              <p className="note dim" style={{ marginTop: 2 }}>
                {detail.n_mic_censored} further MIC
                {detail.n_mic_censored === 1 ? " is" : "s are"} censored: the MIC was not reached at the highest concentration tested. These results are excluded from pMIC.
              </p>
            )}
            <WholeCellConditions detail={detail} />
            {detail.chembl_targets.map((t) => (
              <div className="note" key={t.target_id}>
                <span className="mono">{t.target_id}</span> {t.pref_name}{" "}
                {t.evidence === "orthologue" && <span className="chip ortho">orthologue</span>}
                {t.evidence === "orthologue" && (
                  <div>
                    via {t.via_gene ?? t.via_accession} · {t.via_organism} · {t.uniref_cluster},{" "}
                    {Math.round(Number(t.identity_level) * 100)}% cluster of {t.cluster_size} — linked through a UniRef cluster; binding-site similarity has not been assessed.
                  </div>
                )}
              </div>
            ))}
          </>
        ) : (
          <span className="absent">No ChEMBL compound activity is linked to this gene in the dataset</span>
        )}
      </Row>

      <Row label="Drug precedent (fold)" source={SOURCES.precedent}>
        <Precedent detail={detail} />
      </Row>

      <Row label="Clinical stage" source={SOURCES.clinical}>
        {detail.n_drugs ? (
          <>
            <span className="big">{phaseLabel(detail.best_drug_phase)}</span>{" "}
            <span className="dim">for TB · {(detail.drug_names ?? []).join(", ")}</span>
            <div className="note">
              {detail.n_trials} linked trial{detail.n_trials === 1 ? "" : "s"}. A drug counts here only
              when ChEMBL&rsquo;s mechanism or Bosch 2021 names this gene&rsquo;s protein.
            </div>
          </>
        ) : (
          <span className="absent">
            {detail.n_drugs === null
              ? "Clinical data is unavailable in this dataset"
              : "No drug with a TB indication is recorded as acting on this protein"}
            {!!detail.n_complex_drugs &&
              ` (${detail.n_complex_drugs} act on a complex it belongs to)`}
          </span>
        )}
      </Row>

      <Row label="Resistance mutations" source={SOURCES.who}>
        {detail.in_who_catalogue ? (
          <>
            <span className="big">{detail.n_variants_associated}</span>{" "}
            <span className="dim">graded associated with resistance</span>
            <div className="ids" style={{ marginTop: 5 }}>
              {detail.resistance_drugs.map((d) => (
                <span key={d}>{d}</span>
              ))}
            </div>
            <div className="note">
              {detail.n_variants_mappable} of {detail.n_variants_associated} are residue changes that can be mapped to the structure. Promoter changes and protein-disrupting variants are listed without a structure position.
            </div>
          </>
        ) : (
          <span className="absent">not in the catalogue</span>
        )}
      </Row>

      <Row label="Identity" source={SOURCES.identity}>
        <div className="ids">
          <span>{detail.rv_id}</span>
          {detail.uniprot_acc && <span>{detail.uniprot_acc}</span>}
          {detail.length && <span>{detail.length} aa</span>}
          <span>
            {detail.start.toLocaleString()}–{detail.stop.toLocaleString()} {detail.strand}
          </span>
        </div>
        {detail.shares_accession_with.length > 0 && (
          <div className="note">
            Shares its accession with {detail.shares_accession_with.join(", ")} — structures and
            ligands shown here may belong to a sibling locus.
          </div>
        )}
        <div className="note">{detail.category}</div>
        {(detail.pfam_ids.length > 0 || detail.ec_numbers.length > 0) && (
          <div className="ids" style={{ marginTop: 6 }}>
            {detail.ec_numbers.map((e) => (
              <span key={e}>EC {e}</span>
            ))}
            {detail.pfam_ids.map((f) => (
              <span key={f}>{f}</span>
            ))}
          </div>
        )}
      </Row>

      {detail.absences.length > 0 && (
        <Row label="Data coverage">
          {detail.absences.map((text) => (
            <p className="caveat" key={text}>
              {text}
            </p>
          ))}
        </Row>
      )}
    </>
  );
}

function PlddtBar({ predicted }: { predicted: NonNullable<Detail["alphafold"]> }) {
  const bands: [number | null, string, string][] = [
    [predicted.plddt_very_high, "#1f6fd0", "very high"],
    [predicted.plddt_confident, "#49b8e8", "confident"],
    [predicted.plddt_low, "#f3c13a", "low"],
    [predicted.plddt_very_low, "#e8703a", "very low"],
  ];
  return (
    <>
      <div className="bar" role="img" aria-label="pLDDT confidence bands">
        {bands.map(([fraction, colour, label]) => (
          <i
            key={label}
            title={`${label}: ${Math.round((fraction ?? 0) * 100)}%`}
            style={{ background: colour, width: `${(fraction ?? 0) * 100}%` }}
          />
        ))}
      </div>
      <div className="note">
        {Math.round((predicted.plddt_very_high ?? 0) * 100)}% very high ·{" "}
        {Math.round((predicted.plddt_very_low ?? 0) * 100)}% very low
      </div>
    </>
  );
}

/** The same knockdown series in HN878, a clinical isolate.
 *
 * Three states, kept apart on purpose: measured here, measured in H37Rv and
 * never in HN878, and measured in both with no differential reported. The
 * middle one is the common case and the easiest to misread as agreement.
 */
function ClinicalStrain({ detail }: { detail: Detail }) {
  const clinical = detail.hn878_vulnerability_index;
  if (clinical === null || clinical === undefined) {
    return (
      <p className="caveat">
        No HN878 vulnerability measurement is available for this gene in Bosch 2021.
      </p>
    );
  }
  const delta = detail.hn878_delta_vi;
  const direction = delta === null ? null : delta > 0 ? "less" : "more";
  return (
    <div className="note" style={{ color: "var(--fg)" }}>
      In <b>HN878</b>, a Beijing-lineage clinical isolate:{" "}
      <b style={{ color: detail.hn878_vi_certain ? "var(--accent)" : "var(--fg-dim)" }}>
        {clinical.toFixed(2)}
      </b>
      {!detail.hn878_vi_certain && <span className="dim"> (below the study’s confidence threshold)</span>}
      {delta !== null && direction !== null && (
        <>
          {" — "}
          <b>
            {Math.abs(delta).toFixed(1)} {direction} vulnerable
          </b>{" "}
          than in H37Rv, according to the difference reported by Bosch 2021.
        </>
      )}
      {delta === null && (
        <span className="dim">
          {" "}
          — Bosch 2021 reports both measurements but no statistical comparison between strains.
        </span>
      )}
    </div>
  );
}

function BoundLigands({
  detail,
  viewing,
  onView,
  onOpen,
}: {
  detail: Detail;
  viewing: { pdbId: string | null; comp: string | null };
  onView: (pdbId: string, comp: string) => void;
  onOpen: (focus: Focus) => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  // Defaulted, not asserted: an older API is a degraded page, not a blank one.
  const ligands = detail.bound_ligands ?? [];
  // Which of this protein's own entries hold each ligand, best resolved first:
  // the one a click opens. Half are in a single entry; one is in 34.
  const entries = useMemo(() => {
    const byComp = new Map<string, Detail["structures"]>();
    const ranked = [...detail.structures].sort(
      (a, b) => (a.resolution ?? Infinity) - (b.resolution ?? Infinity),
    );
    for (const s of ranked) {
      for (const comp of s.ligand_ids) byComp.set(comp, [...(byComp.get(comp) ?? []), s]);
    }
    return byComp;
  }, [detail.structures]);
  if (!ligands.length) return null;
  return (
    <div className="scroller" style={{ marginTop: 12 }}>
      <p className="lab">Bound on this protein&rsquo;s chains</p>
      <table className="bound">
        <thead>
          <tr>
            <th aria-label="Structure" />
            <th>Ligand</th>
            <th title="This protein's entries with the ligand on its chains, best resolved first">
              Seen in
            </th>
            <th className="n" title="Best pChEMBL measured on this protein, not on any target">
              pChEMBL
            </th>
          </tr>
        </thead>
        <tbody>
          {ligands.map((l) => {
            const seen = entries.get(l.comp_id) ?? [];
            const open = expanded.has(l.comp_id);
            const shown = open ? seen : seen.slice(0, 3);
            const on = viewing.comp === l.comp_id;
            return (
              <tr key={l.comp_id} aria-selected={on}>
                <td>
                  <Structure smiles={l.smiles} width={112} height={60} title={l.name ?? l.comp_id} />
                </td>
                <td>
                  {l.drug_name && l.molecule_chembl_id && (
                    <button
                      type="button"
                      className="chip accent"
                      onClick={() => onOpen({ kind: "drug", id: l.molecule_chembl_id as string })}
                    >
                      {l.drug_name} · {phaseLabel(l.max_phase_tb)}
                    </button>
                  )}
                  <div className="prodcell" title={l.name ?? ""}>
                    {l.name ?? <span className="absent">unnamed component</span>}
                  </div>
                  <div className="bound-ids">
                    {seen[0] ? (
                      <button
                        type="button"
                        className="minibtn"
                        aria-pressed={on}
                        title={`Show ${l.comp_id} in ${seen[0].pdb_id}`}
                        onClick={() => onView(seen[0].pdb_id, l.comp_id)}
                      >
                        {l.comp_id} ▸ view
                      </button>
                    ) : (
                      <span className="id">{l.comp_id}</span>
                    )}
                    {l.molecule_chembl_id && <ChemblLink kind="compound" id={l.molecule_chembl_id} />}
                  </div>
                </td>
                <td>
                  <div className="bound-entries">
                    {shown.map((s) => (
                      <button
                        key={s.pdb_id}
                        type="button"
                        className="minibtn"
                        aria-pressed={on && viewing.pdbId === s.pdb_id}
                        onClick={() => onView(s.pdb_id, l.comp_id)}
                      >
                        {s.pdb_id}
                        {s.resolution ? ` ${number(s.resolution, 2)} Å` : ""}
                      </button>
                    ))}
                    {seen.length > 3 && (
                      <button
                        type="button"
                        className="linkbtn"
                        onClick={() =>
                          setExpanded((prev) => {
                            const next = new Set(prev);
                            if (open) next.delete(l.comp_id);
                            else next.add(l.comp_id);
                            return next;
                          })
                        }
                      >
                        {open ? "fewer" : `+${seen.length - 3} more`}
                      </button>
                    )}
                  </div>
                </td>
                <td className="n">{number(l.best_pchembl)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** How the protein was made, which only the deposition says.
 *
 * A structure is already proof that someone produced the protein; this is the
 * part that tells you what to order — the host, the vector, how much of the
 * sequence was expressed, and whether it was the wild-type at all. Empty means
 * the entry does not state it, which is common for older depositions.
 */
function Construct({ structure }: { structure: Record<string, any> }) {
  const hosts: string[] = structure.expression_hosts ?? [];
  const plasmids: string[] = structure.plasmids ?? [];
  const mutations: string[] = structure.mutations ?? [];
  const length: number | null = structure.construct_length ?? null;
  const parts = [length ? `${length} aa` : null, plasmids.join(", ") || null].filter(Boolean);
  if (!parts.length && !mutations.length && !hosts.length) {
    return <td className="faint">—</td>;
  }
  return (
    <td className="dim" title={hosts.join(" · ") || "Expression host not stated"}>
      {parts.join(" · ")}
      {mutations.length > 0 && (
        <>
          {parts.length > 0 && " · "}
          <b title="Engineered: the crystallised sequence is not the wild-type">
            {mutations.join(", ")}
          </b>
        </>
      )}
    </td>
  );
}

/** "No structure" and "nothing to work from" are different claims.
 *
 * 3,146 genes have no entry under their own accession; 449 of them have a
 * mycobacterial neighbour that does, and for 34 the deposited sequence is
 * *identical* and was filed under a CDC 1551, H37Ra or M. bovis accession --
 * the structure is of this protein, and only the key hid it. The two cases are
 * worded differently on purpose, and the identity is always shown, because
 * what a 34%-identical structure is good for is the reader's judgement.
 */
function Borrowed({ detail }: { detail: Detail }) {
  if (!detail.n_orthologue_pdb) return null;
  const identity = detail.closest_orthologue_identity;
  const liganded = detail.n_orthologue_pdb_with_ligand;
  return (
    <div className="note" style={{ marginTop: detail.n_pdb ? 6 : 5 }}>
      {detail.same_sequence_structure ? (
        <>
          <span className="chip ok">same sequence elsewhere</span> {detail.n_orthologue_pdb} entr
          {detail.n_orthologue_pdb === 1 ? "y" : "ies"} of an{" "}
          <b>identical</b> sequence deposited under another accession
          {detail.closest_orthologue_organism ? ` (${detail.closest_orthologue_organism})` : ""}.
        </>
      ) : (
        <>
          {detail.n_pdb ? "Also " : ""}
          {detail.n_orthologue_pdb} entr{detail.n_orthologue_pdb === 1 ? "y" : "ies"} for{" "}
          <b>{detail.closest_orthologue_gene ?? "a relative"}</b>
          {detail.closest_orthologue_organism ? ` of ${detail.closest_orthologue_organism}` : ""}
          {identity !== null && (
            <>
              , <b className="mono">{(identity * 100).toFixed(0)}%</b> identical over{" "}
              <span className="mono">
                {((detail.closest_orthologue_coverage ?? 0) * 100).toFixed(0)}%
              </span>{" "}
              of this protein
            </>
          )}
          .
        </>
      )}
      {detail.best_orthologue_resolution !== null && (
        <>
          {" "}
          Best {number(detail.best_orthologue_resolution)} Å
          {liganded > 0 && `, ${liganded} with a ligand bound`}.
        </>
      )}{" "}
      <span className="faint">Not counted in the structure count above.</span>
    </div>
  );
}

/**
 * Drug precedent for the fold, in the one sentence it can honestly carry.
 *
 * `docs/data-sources.md` keeps "druggable pockets" as an open question because
 * nothing public answers it, and this is not an answer either -- it counts
 * ChEMBL records against *other* proteins that share a Pfam domain with this
 * gene. So the domain is named, the human share is named (tractable chemistry
 * and a selectivity problem are the same fact), and how many Mtb genes share
 * the domain is named, because a shared domain is not a shared binding site.
 */
function Precedent({ detail }: { detail: Detail }) {
  const approved = detail.n_precedent_approved;
  const clinical = detail.n_precedent_clinical ?? 0;
  if (approved === null) {
    return <span className="absent">No Pfam domain annotation is available for this comparison</span>;
  }
  const human = detail.n_precedent_human_target ?? 0;
  const shared = detail.precedent_domain_genes ?? 0;
  const domain = (
    <>
      <b>{detail.precedent_pfam_name ?? detail.precedent_pfam}</b>
      {detail.precedent_pfam_name && detail.precedent_pfam && (
        <span className="faint mono"> {detail.precedent_pfam}</span>
      )}
    </>
  );
  if (!approved && !clinical) {
    return (
      <>
        <span className="absent">none</span>
        <div className="note" style={{ marginTop: 5 }}>
          No approved or clinical-stage drug is recorded against another single protein with these Pfam domains.
          {detail.n_precedent_complex ? (
            <>
              {" "}
              {detail.n_precedent_complex} approved drug
              {detail.n_precedent_complex === 1 ? " is" : "s are"} recorded against a complex or protein family with a shared domain. These records are excluded from the single-protein count.
            </>
          ) : null}
        </div>
      </>
    );
  }
  return (
    <>
      <span className="big">{approved}</span>{" "}
      <span className="dim">
        approved{clinical > 0 && `, ${clinical} clinical`} on another protein with {domain}
      </span>
      {human > 0 && (
        <span className="chip" style={{ marginLeft: 6 }}>
          {human === approved ? "all human targets" : `${human} human`}
        </span>
      )}
      <div className="note" style={{ marginTop: 5 }}>
        {detail.precedent_example && (
          <>
            e.g. <b>{detail.precedent_example}</b>.{" "}
          </>
        )}
        {shared} Mtb gene{shared === 1 ? "" : "s"} carr{shared === 1 ? "ies" : "y"} that domain, and
        a shared domain is not a shared binding site.
        {detail.n_precedent_complex ? (
          <>
            {" "}
            {detail.n_precedent_complex} more against a complex or protein family, not counted.
          </>
        ) : null}{" "}
        <span className="faint">Druggability has not been assessed in this dataset.</span>
      </div>
    </>
  );
}

/**
 * The rows behind the count. `SINGLE PROTEIN` filings first and the complex or
 * protein-family ones after, labelled, because the second kind is shown and
 * never counted: ChEMBL files the ribosome's approved drugs against a target
 * that names all fifty subunits.
 */
function DrugPrecedentTable({ detail }: { detail: Detail }) {
  const rows = detail.drug_precedent ?? [];
  if (rows.length === 0) return null;
  const phase = (value: number | null) =>
    value === null || value < 0 ? "—" : value >= 4 ? "approved" : `phase ${value}`;
  return (
    <>
      <h4 style={{ margin: "18px 0 0" }}>
        Drugs targeting proteins with a shared domain{" "}
        <span className="faint" style={{ fontWeight: 400 }}>
          · other proteins
        </span>
      </h4>
      <p className="note" style={{ margin: "4px 0 0" }}>
        ChEMBL drug mechanisms recorded against other proteins with a shared Pfam domain. These records provide examples of related drug targets. Binding-site similarity and druggability have not been assessed.
      </p>
      <div className="scroller" style={{ marginTop: 10 }}>
        <table>
          <thead>
            <tr>
              <th>Drug</th>
              <th>Phase</th>
              <th>Acts on</th>
              <th>Organism</th>
              <th>Domain</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.pfam_id}-${r.molecule_chembl_id}-${r.target_chembl_id}-${r.accession}`}>
                <td>
                  {r.molecule_name ?? <span className="mono">{r.molecule_chembl_id}</span>}
                  {r.target_type !== "SINGLE PROTEIN" && (
                    <span className="chip" style={{ marginLeft: 6 }} title={r.target_type ?? ""}>
                      not counted
                    </span>
                  )}
                </td>
                <td className="dim">{phase(r.max_phase)}</td>
                <td title={r.mechanism_of_action ?? ""}>{r.target_name}</td>
                <td className="dim">{r.organism}</td>
                <td className="mono faint" title={r.pfam_id}>
                  {r.pfam_name ?? r.pfam_id}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function OrthologueStructureTable({ detail }: { detail: Detail }) {
  const rows = detail.orthologue_structures ?? [];
  if (rows.length === 0) return null;
  return (
    <>
      <h4 style={{ margin: "18px 0 0" }}>
        Related-protein structures{" "}
        <span className="faint" style={{ fontWeight: 400 }}>
          · other accessions
        </span>
      </h4>
      <p className="note" style={{ margin: "4px 0 0" }}>
        Structures of related mycobacterial proteins, identified by sequence similarity. They use their own residue numbering and are excluded from the resistance-mutation viewer.
      </p>
      <div className="scroller" style={{ marginTop: 10 }}>
        <table>
          <thead>
            <tr>
              <th>PDB</th>
              <th>Protein</th>
              <th>Organism</th>
              <th className="n" title="Identity to the Mtb protein over the aligned region">
                Id
              </th>
              <th className="n" title="Fraction of the Mtb protein the alignment covers">
                Cov
              </th>
              <th className="n">Å</th>
              <th>Ligands</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={`${s.via_acc}-${s.pdb_id}`}>
                <td className="id">
                <a href={`https://www.rcsb.org/structure/${s.pdb_id}`} target="_blank" rel="noreferrer">
                  {s.pdb_id}
                </a>
              </td>
                <td>
                  {s.via_gene ?? s.via_acc}
                  {s.relation === "same_sequence" && (
                    <span className="chip ok" style={{ marginLeft: 6 }}>
                      identical
                    </span>
                  )}
                </td>
                <td className="dim">{s.via_organism}</td>
                <td className="n mono">{(s.identity * 100).toFixed(0)}%</td>
                <td className="n mono faint">{(s.coverage * 100).toFixed(0)}%</td>
                <td className="n">{s.resolution ? number(s.resolution, 2) : "—"}</td>
                <td className="mono">
                  {s.ligand_ids.length ? s.ligand_ids.join(" ") : <span className="absent">—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function StructureTable({ detail }: { detail: Detail }) {
  return (
    <div className="scroller" style={{ marginTop: 12 }}>
      <table>
        <thead>
          <tr>
            <th>PDB</th>
            <th>Method</th>
            <th className="n">Å</th>
            <th>Released</th>
            <th>Ligands</th>
            <th>Elsewhere</th>
            <th title="What was expressed, as the deposition states it">Construct</th>
          </tr>
        </thead>
        <tbody>
          {detail.structures.map((s) => (
            <tr key={s.pdb_id}>
              <td className="id">
                <a href={`https://www.rcsb.org/structure/${s.pdb_id}`} target="_blank" rel="noreferrer">
                  {s.pdb_id}
                </a>
              </td>
              <td className="dim">{(s.method ?? "").toLowerCase()}</td>
              <td className="n">{s.resolution ? number(s.resolution, 2) : "—"}</td>
              <td className="mono dim">{s.released}</td>
              <td className="mono">
                {s.ligand_ids.length ? s.ligand_ids.join(" ") : <span className="absent">—</span>}
              </td>
              <td className="mono faint" title="Bound to another chain in the same entry">
                {s.ligand_ids_elsewhere?.length ? s.ligand_ids_elsewhere.join(" ") : "—"}
              </td>
              <Construct structure={s} />
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Under which conditions has this gene's chemistry actually been measured?
 *
 * The genetics side of the atlas answers this already (conditional TnSeq), and
 * the chemistry side could not: every MIC was pooled into one number. ChEMBL
 * has no condition field, so these labels are read from the depositor's prose,
 * which is why `unspecified` is both the commonest answer and shown as its own
 * row rather than assumed to be standard media.
 */
const CONDITION_LABELS: Record<string, string> = {
  caseum: "caseum",
  intracellular: "intracellular (macrophage)",
  non_replicating: "non-replicating / hypoxic",
  alt_carbon: "alternative carbon source",
  nutrient_stress: "nutrient or oxidative stress",
  standard_media: "standard media (named)",
  unspecified: "medium not stated",
};

function WholeCellConditions({ detail }: { detail: Detail }) {
  const rows = (detail.whole_cell_conditions ?? []).filter((c) => c.n > 0);
  if (rows.length === 0) return null;
  const named = rows.filter((c) => c.condition !== "unspecified");
  return (
    <div style={{ marginTop: 6 }}>
      <table className="cond-table">
        <thead>
          <tr>
            <th>Whole-cell condition</th>
            <th className="n">Measurements</th>
            <th className="n">Best pMIC</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.condition}>
              <td>{CONDITION_LABELS[c.condition] ?? c.condition}</td>
              <td className="n">{c.n.toLocaleString()}</td>
              <td className="n">
                {c.best_pmic !== null ? (
                  number(c.best_pmic)
                ) : (
                  <span className="absent" title={`${c.n} measurement(s), none convertible to a pMIC`}>
                    —
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {named.length === 0 && (
        <p className="caveat" style={{ marginTop: 4 }}>
          Growth conditions are unspecified for the MIC measurements linked to this gene.
        </p>
      )}
    </div>
  );
}

/** Can this target be screened at all?
 *
 * Distinct from whether anyone has hit it. A gene with an essentiality call, a
 * structure and no published assay needs the assay built before any of the
 * rest is usable, and that is weeks of work the other panels do not show.
 */
function AssayReadiness({ detail }: { detail: Detail }) {
  const assays = detail.n_protein_assays ?? 0;
  if (!assays) {
    return (
      <p className="caveat" style={{ marginTop: 0 }}>
        No single-protein assay is recorded in ChEMBL for this target. Whole-cell and orthologue assays are listed separately.
      </p>
    );
  }
  const example = detail.protein_assay_example;
  return (
    <p className="note" style={{ marginTop: 0, color: "var(--fg)" }}>
      <b>{assays}</b> published assay{assays === 1 ? "" : "s"} against this protein
      {detail.latest_protein_assay_year ? `, most recent ${detail.latest_protein_assay_year}` : ""}.
      {example && (
        <span className="dim">
          {" "}
          Most used: {example.length > 150 ? `${example.slice(0, 150)}…` : example}
        </span>
      )}
    </p>
  );
}

/** Has anyone screened this protein, and how big was the biggest one?
 *
 * Library size is the question, not hit count: a 350,000-compound campaign and
 * fourteen five-compound follow-ups are opposite answers. An actives count is
 * printed only where that campaign stated calls, and is never divided by the
 * number of campaigns -- the two share no denominator.
 */
function ScreenedIn({ detail, onOpenScreen }: { detail: Detail; onOpenScreen?: (id: string) => void }) {
  const own = detail.screens.filter((s) => s.own);
  const complex = detail.screens.filter((s) => !s.own);
  if (!own.length) {
    return (
      <p className="caveat">
        No campaign in this dataset screened this protein alone
        {complex.length > 0 &&
          `; ${complex.length} screened a complex containing it`}
        .
      </p>
    );
  }
  const biggest = Math.max(...own.map((s) => s.n_tested ?? 0));
  return (
    <>
      <p className="note" style={{ color: "var(--fg)" }}>
        <b>{own.length}</b> screening campaign{own.length === 1 ? "" : "s"} on this protein
        {biggest > 0 && <>, the largest {biggest.toLocaleString()} compounds</>}.
      </p>
      <div className="scroller">
        <table>
          <thead>
            <tr>
              <th>Campaign</th>
              <th>Depositor</th>
              <th className="n">Year</th>
              <th className="n">Tested</th>
              <th className="n">Actives</th>
            </tr>
          </thead>
          <tbody>
            {own.map((s) => (
              <tr key={s.screen_id}>
                <td>
                  <button type="button" className="row-open" onClick={() => onOpenScreen?.(s.screen_id)}>
                    <span className="clinical-clamp" title={s.title ?? undefined}>
                      {s.title ?? s.screen_id}
                    </span>
                  </button>
                </td>
                <td className="dim">{s.depositor ?? "—"}</td>
                <td className="n dim">{s.year ?? "—"}</td>
                <td className="n">{s.n_tested?.toLocaleString() ?? "—"}</td>
                <td className={s.outcome_stated ? "n" : "n dim"}>
                  {!s.outcome_stated ? "no call stated" : (s.n_active?.toLocaleString() ?? "per stage")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {complex.length > 0 && (
        <p className="caveat">
          {complex.length} further campaign{complex.length === 1 ? "" : "s"} screened a complex containing this protein. These records are excluded from the single-protein campaign count.
        </p>
      )}
    </>
  );
}

function Chemistry({ detail, onOpen, onOpenScreen }: {
  detail: Detail;
  onOpen: (focus: Focus) => void;
  onOpenScreen?: (id: string) => void;
}) {
  const byCompound = useMemo(() => {
    const index = new Map<string, Compound>();
    for (const c of detail.compounds) index.set(c.molecule_chembl_id, c);
    // Rank the cell measurement by pMIC, not pchembl_value. ChEMBL leaves
    // pchembl_value null on every MIC, so ranking by it picked a blank row and
    // the column read "—" for compounds that have a perfectly good MIC.
    const cell = new Map<string, Activity>();
    for (const a of detail.whole_cell) {
      const id = a.molecule_chembl_id ?? "";
      const best = cell.get(id);
      const score = (x: Activity) => x.pmic ?? x.pchembl_value ?? 0;
      if (!best || score(a) > score(best)) cell.set(id, a);
    }
    const best = new Map<string, Activity>();
    for (const a of detail.activities) {
      const id = a.molecule_chembl_id ?? "";
      const current = best.get(id);
      if (!current || (a.pchembl_value ?? 0) > (current.pchembl_value ?? 0)) best.set(id, a);
    }
    return [...best.values()]
      .sort((a, b) => (b.pchembl_value ?? 0) - (a.pchembl_value ?? 0))
      .map((activity) => ({
        activity,
        compound: index.get(activity.molecule_chembl_id ?? ""),
        cell: cell.get(activity.molecule_chembl_id ?? ""),
      }));
  }, [detail]);

  if (!byCompound.length) {
    return (
      <>
        <AssayReadiness detail={detail} />
        <ScreenedIn detail={detail} onOpenScreen={onOpenScreen} />
        <p className="absent">
          No ChEMBL compound activity is linked to this gene in the dataset.
        </p>
        <DrugPrecedentTable detail={detail} />
      </>
    );
  }

  return (
    <>
      <AssayReadiness detail={detail} />
      <ScreenedIn detail={detail} onOpenScreen={onOpenScreen} />
      <p className="note" style={{ marginTop: 0 }}>
        Best measurement per compound. Whole-cell potency is shown only for compounds that already
        have protein-level activity here.
      </p>
      <div className="scroller">
        <table>
          <thead>
            <tr>
              <th>Structure</th>
              <th>Compound</th>
              <th className="n">pChEMBL</th>
              <th>Type</th>
              <th className="n">Cell</th>
              <th className="n">MW</th>
              <th className="n">cLogP</th>
              <th>Phase</th>
              <th>Measured by</th>
            </tr>
          </thead>
          <tbody>
            {/* All of them: the tab badge counts 356 for inhA and a table
                that stopped at 250 was claiming a number it did not show.
                Each depiction waits until it scrolls into view, so the cost
                is the rows, not the molecules. */}
            {byCompound.map(({ activity, compound, cell }) => (
              <tr
                key={activity.molecule_chembl_id}
                onClick={() =>
                  activity.molecule_chembl_id &&
                  onOpen({ kind: "compound", id: activity.molecule_chembl_id })
                }
              >
                <td>
                  <Structure
                    smiles={compound?.smiles}
                    title={compound?.pref_name ?? activity.molecule_chembl_id ?? undefined}
                  />
                </td>
                <td className="id">
                  {/* Most of these have no name, so the accession is the name:
                      printing it twice is noise, not provenance. */}
                  {compound?.pref_name && <div>{compound.pref_name}</div>}
                  {activity.molecule_chembl_id && (
                    <ChemblLink kind="compound" id={activity.molecule_chembl_id} />
                  )}
                  {activity.evidence === "orthologue" && (
                    <span className="chip ortho" style={{ marginLeft: 5 }}>
                      orth
                    </span>
                  )}
                  {activity.data_validity_comment && (
                    <span className="chip warn" style={{ marginLeft: 5 }} title={activity.data_validity_comment}>
                      flagged
                    </span>
                  )}
                </td>
                <td className="n">{number(activity.pchembl_value)}</td>
                <td className="dim">{activity.standard_type}</td>
                {/* pMIC where there is one, else the whole-cell pChEMBL. The
                    title says which, because they are different endpoints. */}
                <td className="n" title={cell ? (cell.pmic !== null ? `pMIC from ${cell.standard_type} ${cell.standard_value} ${cell.standard_units} (${cell.pmic_basis})` : "whole-cell pChEMBL") : undefined}>
                  {cell ? number(cell.pmic ?? cell.pchembl_value) : "—"}
                  {cell?.resistant_panel && (
                    <span className="chip" style={{ marginLeft: 4 }} title="measured on a resistant or clinical isolate">
                      res
                    </span>
                  )}
                </td>
                <td className="n">{number(compound?.mw ?? null, 0)}</td>
                <td className="n">{number(compound?.alogp ?? null, 1)}</td>
                <td className="dim">{phaseLabel(compound?.max_phase ?? null)}</td>
                {/* A number is only as good as the experiment behind it, and
                    "which assay" is the first thing anyone asks of an IC50. */}
                <td className="assaycell">
                  <div title={activity.assay_description ?? undefined}>
                    {activity.assay_description ?? <span className="absent">—</span>}
                  </div>
                  <span className="assaylinks">
                    {activity.assay_chembl_id && (
                      <ChemblLink kind="assay" id={activity.assay_chembl_id} />
                    )}
                    {activity.document_chembl_id && (
                      <ChemblLink
                        kind="document"
                        id={activity.document_chembl_id}
                        label={activity.document_year ? `paper ${activity.document_year}` : "paper"}
                      />
                    )}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <DrugPrecedentTable detail={detail} />
    </>
  );
}

function Resistance({ detail, onFocus }: { detail: Detail; onFocus: (position: number) => void }) {
  if (!detail.variants.length) {
    return (
      <p className="absent">
        {detail.gene_name ?? detail.rv_id} has no graded variants in the included WHO catalogue records.
      </p>
    );
  }
  const grouped = new Map<string, Variant[]>();
  for (const variant of detail.variants) {
    const list = grouped.get(variant.mutation) ?? [];
    list.push(variant);
    grouped.set(variant.mutation, list);
  }
  return (
    <>
      <p className="note" style={{ marginTop: 0 }}>
        {detail.n_variants_mappable} of {grouped.size} graded variants are residue changes. Click one
        to locate it in the structure.
      </p>
      <div className="scroller">
        <table>
          <thead>
            <tr>
              <th>Variant</th>
              <th>Grading</th>
              <th>Effect</th>
              <th>Drugs</th>
              <th>On structure</th>
            </tr>
          </thead>
          <tbody>
            {[...grouped.entries()].map(([mutation, group]) => {
              const first = group[0];
              return (
                <tr
                  key={mutation}
                  onClick={() => first.residue_position && onFocus(first.residue_position)}
                  style={{ cursor: first.residue_position ? "pointer" : "default" }}
                >
                  <td className="id">{mutation}</td>
                  <td>
                    <span className={`chip ${first.grading.startsWith("1") ? "accent" : "warn"}`}>
                      {first.grading.replace(/^\d\) /, "")}
                    </span>
                  </td>
                  <td className="dim">{first.effect?.replace(/_/g, " ")}</td>
                  <td className="mono">{[...new Set(group.map((v) => v.drug))].join(", ")}</td>
                  <td className="mono">
                    {first.residue_label ?? <span className="absent">not a residue</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}


function Network({ detail }: { detail: Detail }) {
  if (!detail.partners.length) {
    return (
      <p className="absent">
        No STRING partner meets the combined-score threshold of 700 used here.
      </p>
    );
  }
  return (
    <>
      <p className="note" style={{ marginTop: 0 }}>
        STRING functional associations with a combined score ≥ 700. Scores for experimental evidence, curated databases, co-expression and text mining are shown separately.
      </p>
      <div className="scroller">
        <table>
          <thead>
            <tr>
              <th>Partner</th>
              <th>Gene</th>
              <th className="n">Score</th>
              <th className="n">Experimental</th>
              <th className="n">Database</th>
              <th className="n">Co-expr.</th>
              <th className="n">Text</th>
            </tr>
          </thead>
          <tbody>
            {detail.partners.map((p) => (
              <tr key={p.rv_id}>
                <td className="id">{p.rv_id}</td>
                <td>{p.gene_name && p.gene_name !== p.rv_id ? p.gene_name : "—"}</td>
                <td className="n">{p.combined_score}</td>
                <td className="n">{p.experimental || "—"}</td>
                <td className="n">{p.database || "—"}</td>
                <td className="n">{p.coexpression || "—"}</td>
                <td className="n faint">{p.textmining || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
