import { useEffect, useMemo, useState } from "react";
import { api, type ProteinAssay } from "./api";
import { ChemblLink } from "./Structure";

/** Read the full census, including assays without a potency measurement. */
export function ProteinAssays({ rvId }: { rvId: string }) {
  const [assays, setAssays] = useState<ProteinAssay[] | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState("");
  useEffect(() => {
    let current = true;
    setAssays(null);
    setError(false);
    setQuery("");
    api.proteinAssays(rvId).then(rows => { if (current) setAssays(rows); })
      .catch(() => { if (current) setError(true); });
    return () => { current = false; };
  }, [rvId, attempt]);
  const filtered = useMemo(() => assays?.filter(assay =>
    [assay.assay_chembl_id, assay.description, ...assay.endpoint_types].join(" ").toLowerCase().includes(query.trim().toLowerCase()),
  ) ?? [], [assays, query]);

  if (error) return <div className="protein-assays-state" role="alert">Could not load protein assays. <button type="button" className="rowbtn" onClick={() => setAttempt(n => n + 1)}>Retry</button></div>;
  if (assays === null) return <p className="protein-assays-state" role="status">Loading protein assays…</p>;
  if (!assays.length) return <p className="protein-assays-state">No single-protein assays recorded for this target.</p>;

  return (
    <section className="protein-assays" aria-label="Protein assay records">
      <div className="protein-assays-heading"><h4>Protein assays <span>{assays.length.toLocaleString()}</span></h4><span>Largest assays first</span></div>
      {assays.length > 8 && <input className="search" type="search" aria-label="Search protein assays" placeholder="Search assay or endpoint…" value={query} onChange={event => setQuery(event.target.value)} />}
      <div className="protein-assay-list">
        {filtered.map(assay => <article className="protein-assay" key={assay.assay_chembl_id}>
          <div className="protein-assay-heading"><ChemblLink kind="assay" id={assay.assay_chembl_id} /><span>{assay.latest_year ?? "Year not recorded"}</span></div>
          <p>{assay.description ?? "Description unavailable."}</p>
          <dl><div><dt>Compounds</dt><dd>{assay.n_compounds.toLocaleString()}</dd></div><div><dt>Measurements</dt><dd>{assay.n_measurements.toLocaleString()}</dd></div></dl>
          {!!assay.endpoint_types.length && <div className="chips">{assay.endpoint_types.map(endpoint => <span className="chip" key={endpoint}>{endpoint}</span>)}</div>}
          {!!assay.document_ids.length && <div className="protein-assay-papers">{assay.document_ids.map(id => <ChemblLink key={id} kind="document" id={id} label={`Paper ${id}`} />)}</div>}
        </article>)}
        {!filtered.length && <p className="protein-assays-state">No assays match this search.</p>}
      </div>
      <p className="protein-assays-source">ChEMBL · CC BY-SA 3.0{[...new Set(assays.map(a => a.source_version).filter(Boolean))].map(version => <span key={version}> · {version}</span>)}</p>
    </section>
  );
}
