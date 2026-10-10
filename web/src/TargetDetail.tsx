/**
 * Everything the atlas knows about one gene, including what it does not know.
 *
 * Every number carries the source it came from. Absences are rendered as
 * statements ("not in the WHO catalogue, which covers 65 genes") rather than
 * as blank cells, because "essential, has a structure, no ligands" is a result
 * this app exists to produce and a zero has to be trustworthy.
 */

import { useEffect, useMemo, useState } from "react";
import type { Activity, Compound, TargetDetail as Detail, Meta, Variant } from "./api";
import { ClinicalTab, phaseLabel, type Focus } from "./Clinical";
import { StructureViewer, alphafoldSource, pdbSource, type ViewerSource } from "./StructureViewer";

const SOURCES = {
  essentiality: "DeJesus 2017, mBio · Table S3 · CC BY 4.0",
  pdb: "RCSB PDB · CC0 1.0",
  alphafold: "AlphaFold DB v6 · CC BY 4.0",
  chembl: "ChEMBL 37 · CC BY-SA 3.0",
  who: "WHO catalogue 2nd ed. 2023 · ODC-By 1.0",
  vulnerability: "Bosch et al. 2021, Cell · Table S3 · CC BY 4.0",
  string: "STRING v12.5 · CC BY 4.0",
  homology: "phmmer vs reviewed human proteome (UniProt) · CC BY 4.0",
  identity: "Mycobrowser release 5 (licence not stated) · UniProt · CC BY 4.0",
  clinical: "ChEMBL TB indications and mechanisms · Bosch 2021 · ClinicalTrials.gov",
  uniprot: "UniProt · CC BY 4.0",
};

type Tab = "evidence" | "structure" | "chemistry" | "resistance" | "clinical" | "network";

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

export function TargetDetailPanel({
  detail,
  meta,
  onOpen,
}: {
  detail: Detail;
  meta: Meta | null;
  onOpen: (focus: Focus) => void;
}) {
  const [tab, setTab] = useState<Tab>("evidence");
  const [structureIndex, setStructureIndex] = useState(0);
  const [showLigands, setShowLigands] = useState(true);
  const [showResistance, setShowResistance] = useState(true);
  const [focusResidue, setFocusResidue] = useState<number | null>(null);

  useEffect(() => {
    setStructureIndex(0);
    setFocusResidue(null);
  }, [detail.rv_id]);

  const sources: ViewerSource[] = useMemo(() => {
    const list = detail.structures
      .slice(0, 12)
      .map((s) => pdbSource(s.pdb_id, s.title));
    if (detail.alphafold?.cif_url && detail.alphafold.entry_id) {
      list.push(alphafoldSource(detail.alphafold.cif_url, detail.alphafold.entry_id));
    }
    return list;
  }, [detail]);

  const mappable = detail.variants.filter((v) => v.residue_position !== null);

  return (
    <>
      <div className="detailhead">
        <div className="row">
          <span className="rv">{detail.rv_id}</span>
          {detail.gene_name && detail.gene_name !== detail.rv_id && (
            <span className="gn">{detail.gene_name}</span>
          )}
          {detail.conflict && <span className="chip warn">{detail.acc_status?.replace(/_/g, " ")}</span>}
          {detail.is_pseudogene && <span className="chip warn">pseudogene</span>}
        </div>
        <p>{detail.product}</p>
      </div>

      <div className="tabs">
        {(
          [
            ["evidence", "Evidence", null],
            ["structure", "Structure", detail.n_pdb + (detail.has_predicted ? 1 : 0)],
            ["chemistry", "Chemistry", detail.n_compounds],
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

      <div className="panel">
        {tab === "evidence" && <Evidence detail={detail} />}

        {tab === "structure" && (
          <>
            {sources.length === 0 ? (
              <p className="absent">
                No experimental structure and no AlphaFold model for this accession.
              </p>
            ) : (
              <>
                <div className="viewerbar">
                  {sources.slice(0, 8).map((s, i) => (
                    <button
                      key={s.id}
                      type="button"
                      className="minibtn"
                      aria-pressed={i === structureIndex}
                      onClick={() => setStructureIndex(i)}
                    >
                      {s.id}
                    </button>
                  ))}
                </div>
                <StructureViewer
                  source={sources[structureIndex] ?? null}
                  variants={detail.variants}
                  showLigands={showLigands}
                  showResistance={showResistance}
                  focusResidue={focusResidue}
                />
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
                    {sources[structureIndex]?.predicted ? "pLDDT confidence" : "backbone"}
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
                <StructureTable detail={detail} />
              </>
            )}
          </>
        )}

        {tab === "chemistry" && <Chemistry detail={detail} />}

        {tab === "clinical" && <ClinicalTab detail={detail} meta={meta} onOpen={onOpen} />}

        {tab === "network" && <Network detail={detail} />}

        {tab === "resistance" && (
          <Resistance detail={detail} onFocus={(position) => {
            setTab("structure");
            setFocusResidue(position);
          }} />
        )}
      </div>
    </>
  );
}

function Protein({ detail }: { detail: Detail }) {
  const [open, setOpen] = useState(false);
  if (!detail.uniprot_acc) {
    return (
      <Row label="Protein">
        <span className="absent">no protein: this is an RNA gene, or no accession could be resolved</span>
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
        {detail.locations.map((l) => (
          <span key={l}>{l}</span>
        ))}
        <span>
          {detail.n_transmembrane
            ? `${detail.n_transmembrane} transmembrane segment${detail.n_transmembrane === 1 ? "" : "s"}`
            : "no transmembrane segment annotated"}
        </span>
        {detail.signal_peptide && <span>signal peptide</span>}
      </div>
      {detail.pathways.map((p) => (
        <div className="note" key={p} style={{ color: "var(--fg)" }}>
          Pathway: {p}
        </div>
      ))}
      {detail.reactions.slice(0, 2).map((r) => (
        <div className="note mono" key={r}>
          {r}
        </div>
      ))}
      {detail.cofactors.length > 0 && <div className="note">Cofactor: {detail.cofactors.join(", ")}</div>}
      {detail.go_process.length > 0 && (
        <div className="note">Process: {detail.go_process.slice(0, 6).join(" · ")}</div>
      )}
      {detail.disruption_phenotype && <p className="caveat">Disruption: {detail.disruption_phenotype}</p>}
      <div className="note">
        UniProt cites {detail.pubmed_ids.length} paper{detail.pubmed_ids.length === 1 ? "" : "s"} for this
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
              {detail.ta_sites ?? "—"} TA sites. One condition: {detail.essentiality_condition}.
            </div>
          </>
        ) : (
          <span className="absent">no call in this dataset</span>
        )}
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
              More negative is more vulnerable: how far expression has to fall before fitness
              suffers, which is the question an inhibitor poses. Essentiality only says whether the
              gene can be deleted.
            </div>
            {!detail.vulnerability_certain && (
              <p className="caveat">
                This estimate did not meet the study&rsquo;s own criteria for confidence — only ~600
                genes do. Treat it as indicative.
              </p>
            )}
            {detail.antibacterial && (
              <div className="note" style={{ color: "var(--fg)" }}>
                Already targeted by <b>{detail.antibacterial}</b>.
              </div>
            )}
          </>
        )}
      </Row>

      <Row label="Human homolog" source={SOURCES.homology}>
        {detail.human_homolog ? (
          <>
            <span className={`chip ${detail.close_human_homolog ? "warn" : "ortho"}`}>
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
                ? "Close enough to be a selectivity liability worth checking early."
                : "A detectable but distant relative. Below the 30% line this atlas draws for a close homolog — that line is a convention here, not a fact of biology."}
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
          <span className="absent">none</span>
        )}
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
              {detail.best_whole_cell_pchembl !== null && (
                <> · best whole-cell pChEMBL <b className="mono">{number(detail.best_whole_cell_pchembl)}</b></>
              )}
            </div>
            {detail.chembl_targets.map((t) => (
              <div className="note" key={t.target_id}>
                <span className="mono">{t.target_id}</span> {t.pref_name}{" "}
                {t.evidence === "orthologue" && <span className="chip ortho">orthologue</span>}
                {t.evidence === "orthologue" && (
                  <div>
                    via {t.via_gene ?? t.via_accession} · {t.via_organism} · {t.uniref_cluster},{" "}
                    {Math.round(Number(t.identity_level) * 100)}% cluster of {t.cluster_size} — a
                    family-level link, not evidence of a shared binding site.
                  </div>
                )}
              </div>
            ))}
          </>
        ) : (
          <span className="absent">no compound in ChEMBL is recorded against this gene</span>
        )}
      </Row>

      <Row label="Clinical stage" source={SOURCES.clinical}>
        {detail.n_drugs ? (
          <>
            <span className="big">{phaseLabel(detail.best_drug_phase)}</span>{" "}
            <span className="dim">for TB · {detail.drug_names.join(", ")}</span>
            <div className="note">
              {detail.n_trials} linked trial{detail.n_trials === 1 ? "" : "s"}. A drug counts here only
              when ChEMBL&rsquo;s mechanism or Bosch 2021 names this gene&rsquo;s protein.
            </div>
          </>
        ) : (
          <span className="absent">
            no drug with a TB indication acts on this gene
            {detail.n_complex_drugs > 0 &&
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
              {detail.n_variants_mappable} of {detail.n_variants_associated} are residue changes; the
              rest change the promoter or break the protein, and no structure can show those.
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
        <Row label="What the atlas does not know">
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
          </tr>
        </thead>
        <tbody>
          {detail.structures.map((s) => (
            <tr key={s.pdb_id}>
              <td className="id">{s.pdb_id}</td>
              <td className="dim">{(s.method ?? "").toLowerCase()}</td>
              <td className="n">{s.resolution ? number(s.resolution, 2) : "—"}</td>
              <td className="mono dim">{s.released}</td>
              <td className="mono">
                {s.ligand_ids.length ? s.ligand_ids.join(" ") : <span className="absent">—</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Chemistry({ detail }: { detail: Detail }) {
  const byCompound = useMemo(() => {
    const index = new Map<string, Compound>();
    for (const c of detail.compounds) index.set(c.molecule_chembl_id, c);
    const cell = new Map<string, Activity>();
    for (const a of detail.whole_cell) {
      const id = a.molecule_chembl_id ?? "";
      const best = cell.get(id);
      if (!best || (a.pchembl_value ?? 0) > (best.pchembl_value ?? 0)) cell.set(id, a);
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
      <p className="absent">
        No ChEMBL activity against this gene. If it is essential and has a structure, that is the
        interesting kind of nothing.
      </p>
    );
  }

  return (
    <>
      <p className="note" style={{ marginTop: 0 }}>
        Best measurement per compound. Whole-cell potency is shown only for compounds that already
        have protein-level activity here.
      </p>
      <div className="scroller">
        <table>
          <thead>
            <tr>
              <th>Compound</th>
              <th className="n">pChEMBL</th>
              <th>Type</th>
              <th className="n">Cell</th>
              <th className="n">MW</th>
              <th className="n">cLogP</th>
              <th>Phase</th>
            </tr>
          </thead>
          <tbody>
            {byCompound.slice(0, 250).map(({ activity, compound, cell }) => (
              <tr key={activity.molecule_chembl_id}>
                <td className="id">
                  {compound?.pref_name ?? activity.molecule_chembl_id}
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
                <td className="n">{cell ? number(cell.pchembl_value) : "—"}</td>
                <td className="n">{number(compound?.mw ?? null, 0)}</td>
                <td className="n">{number(compound?.alogp ?? null, 1)}</td>
                <td className="dim">{compound?.max_phase ? `phase ${compound.max_phase}` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Resistance({ detail, onFocus }: { detail: Detail; onFocus: (position: number) => void }) {
  if (!detail.variants.length) {
    return (
      <p className="absent">
        {detail.gene_name ?? detail.rv_id} is not among the WHO catalogue's 65 genes — those with
        matched phenotypic drug-susceptibility testing — so there are no graded variants to place on
        a structure.
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
        to swing the structure onto it.
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
        No high-confidence STRING partners. Edges below a combined score of 700 are left out: the
        full network is mostly low-confidence text mining and would bury the real links.
      </p>
    );
  }
  return (
    <>
      <p className="note" style={{ marginTop: 0 }}>
        STRING functional partners, combined score ≥ 700. A score built only from text mining is a
        much weaker claim than one with experimental support, so the channels are shown separately.
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
