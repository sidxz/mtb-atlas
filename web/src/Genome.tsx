/**
 * The locus on the chromosome: igv.js around the gene, then its DNA and protein.
 *
 * igv is imported on first use, so nobody who never opens this tab pays for it.
 * The reference is NC_000962.3 as the API serves it, the record Mycobrowser's
 * coordinates are on. Operons are not drawn: no source in docs/data-sources.md
 * states one, and adjacency on a strand is not an operon call.
 */
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { api, BASE, type GeneSequence } from "./api";

// Enough flank to show the neighbours a gene is usually read with.
const FLANK = 5000;

function Browser({ seq }: { seq: GeneSequence }) {
  const host = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let browser: { on: Function } | null = null;
    let removed = false;
    let igvModule: typeof import("igv").default | null = null;
    (async () => {
      const [{ default: igv }, features] = await Promise.all([import("igv"), api.genomeFeatures()]);
      if (removed || !host.current) return;
      igvModule = igv;
      const locus = `${seq.dna?.accession ?? "NC_000962.3"}:${Math.max(1, seq.start - FLANK)}-${seq.stop + FLANK}`;
      browser = await igv.createBrowser(host.current, {
        reference: {
          id: "NC_000962.3",
          name: "M. tuberculosis H37Rv (NC_000962.3)",
          fastaURL: new URL(`${BASE}/genome/sequence.fa`, window.location.origin).href,
          indexed: false,
        },
        locus,
        tracks: [
          {
            name: "Genes (Mycobrowser)",
            type: "annotation",
            displayMode: "EXPANDED",
            searchable: true,
            searchableFields: ["name", "rv_id"],
            features: features.filter((f) => f.track === "gene"),
          },
          {
            name: "Promoters, -10/-35 (Mycobrowser)",
            type: "annotation",
            displayMode: "EXPANDED",
            color: "#b5651d",
            features: features.filter((f) => f.track === "regulatory"),
          },
        ],
      } as any);
      if (removed) {
        igv.removeBrowser(browser as any);
        return;
      }
      // A click on a neighbouring gene opens it; anything else gets igv's own popup.
      browser.on("trackclick", (track: { name?: string }, popover: unknown) => {
        if (!track.name?.startsWith("Genes") || !Array.isArray(popover)) return undefined;
        const rv = popover.find((item) => String(item?.name).toLowerCase() === "rv_id")?.value;
        if (!rv || rv === seq.rv_id) return undefined;
        navigate(`/genome/${encodeURIComponent(rv)}`);
        return false;
      });
    })().catch(() => !removed && setFailed(true));
    return () => {
      removed = true;
      if (browser && igvModule) igvModule.removeBrowser(browser as any);
    };
  }, [seq.rv_id]);

  if (failed) return <p className="absent" role="alert">The genome browser could not load.</p>;
  return <div ref={host} className="genome-browser" aria-label={`Genome around ${seq.rv_id}`} />;
}

function SequenceBlock({ title, header, sequence, source }: {
  title: string;
  header: string;
  sequence: string;
  source: string;
}) {
  const fasta = `>${header}\n${sequence.match(/.{1,60}/g)?.join("\n") ?? ""}\n`;
  const [copied, setCopied] = useState(false);
  return (
    <section className="sequence-block">
      <div className="sequence-head">
        <h4>{title} <span>{sequence.length.toLocaleString()}</span></h4>
        <span className="src">{source}</span>
        <button type="button" className="minibtn" onClick={() => {
          navigator.clipboard.writeText(fasta).then(() => setCopied(true), () => setCopied(false));
        }}>{copied ? "copied" : "copy FASTA"}</button>
      </div>
      <pre className="sequence">{sequence}</pre>
    </section>
  );
}

export function Genome({ rvId }: { rvId: string }) {
  const [seq, setSeq] = useState<GeneSequence | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let current = true;
    setSeq(null);
    setError(false);
    api.sequence(rvId).then((s) => current && setSeq(s)).catch(() => current && setError(true));
    return () => { current = false; };
  }, [rvId]);

  if (error) return <p className="absent" role="alert">Could not load this locus.</p>;
  if (!seq) return <p role="status">Loading the locus…</p>;
  const label = seq.gene_name && seq.gene_name !== seq.rv_id ? `${seq.rv_id} ${seq.gene_name}` : seq.rv_id;
  return (
    <>
      <p className="note">
        {seq.dna?.accession ?? "NC_000962.3"}:{seq.start.toLocaleString()}–{seq.stop.toLocaleString()} ({seq.strand}).
        Click a neighbouring gene to open it. Operons are not drawn: no source here states one.
      </p>
      {seq.dna ? <Browser seq={seq} /> : <p className="absent">The genome is not built in this store.</p>}
      {seq.dna && (
        <SequenceBlock
          title="DNA"
          header={`${label} ${seq.dna.accession}:${seq.start}-${seq.stop}(${seq.strand})`}
          sequence={seq.dna.sequence}
          source={`NCBI ${seq.dna.source_version}, coding strand`}
        />
      )}
      {seq.protein ? (
        <SequenceBlock
          title="Protein"
          header={`${label} ${seq.protein.uniprot_acc}`}
          sequence={seq.protein.sequence}
          source={`UniProt ${seq.protein.uniprot_acc}, ${seq.protein.source_version}`}
        />
      ) : (
        <p className="absent">
          {seq.feature === "CDS" ? "No UniProt protein for this locus." : `An ${seq.feature} gene: no protein.`}
        </p>
      )}
    </>
  );
}
