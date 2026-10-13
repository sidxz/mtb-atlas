/**
 * What a public site owes its visitors: whose data this is, what is stored and
 * sent where, and what the atlas does not promise. Written so any operator can
 * run it unchanged; who runs this instance comes from /meta.
 */
import { useState } from "react";
import { Link } from "react-router";
import type { Meta } from "./api";

const REPO = "https://github.com/sidxz/mtb-atlas";
const NOTICE_KEY = "atlas.notice.v1";

/** The citations the sources ask for, verbatim from docs/data-sources.md. */
const CITATIONS: { source: string; cite: string; doi: string }[] = [
  { source: "Mycobrowser", cite: "Kapopoulou A, Lew JM, Cole ST. The MycoBrowser portal: a comprehensive and manually annotated resource for mycobacterial genomes. Tuberculosis (Edinb) 2011;91(1):8–13.", doi: "10.1016/j.tube.2010.09.006" },
  { source: "Essentiality", cite: "DeJesus MA, Gerrick ER, Xu W, et al. Comprehensive essentiality analysis of the Mycobacterium tuberculosis genome via saturating transposon mutagenesis. mBio 2017;8(1):e02133-16.", doi: "10.1128/mBio.02133-16" },
  { source: "CRISPRi vulnerability", cite: "Bosch B, DeJesus MA, Poulton NC, et al. Genome-wide gene expression tuning reveals diverse vulnerabilities of M. tuberculosis. Cell 2021;184(17):4579–4592.e24.", doi: "10.1016/j.cell.2021.06.033" },
  { source: "Conditional fitness", cite: "Griffin JE, Gawronski JD, DeJesus MA, Ioerger TR, Akerley BJ, Sassetti CM. High-resolution phenotypic profiling defines genes essential for mycobacterial growth and cholesterol catabolism. PLoS Pathog 2011;7(9):e1002251.", doi: "10.1371/journal.ppat.1002251" },
  { source: "MtbTnDB", cite: "Jinich A, Zaveri A, DeJesus MA, et al. The Mycobacterium tuberculosis Transposon Sequencing Database (MtbTnDB): a large-scale guide to genetic conditional essentiality. Mol Microbiol 2025;124(1):91–101.", doi: "10.1111/mmi.15370" },
];

function Sources({ meta }: { meta: Meta | null }) {
  return (
    <>
      <h2>Sources &amp; licences</h2>
      <p>Every value in the atlas comes from a public source, and each keeps its own licence. The table is this instance's store: the release each source was built from and when it was retrieved.</p>
      <ul>
        <li><strong>ChEMBL</strong> and everything derived from it (bioactivity, drugs and mechanisms, drug precedent, hit profiling, the ChEMBL–PubChem bridge) is <strong>CC BY-SA 3.0</strong>, and that content is shared here under the same licence.</li>
        <li><strong>ClinicalTrials.gov</strong> data is shown as retrieved on the date below. Its display here does not imply endorsement by the U.S. National Library of Medicine.</li>
        <li><strong>PubChem</strong> screening results belong to their depositors; every campaign names its depositor, and no blanket licence is claimed.</li>
        <li><strong>Mycobrowser</strong> states no licence. The atlas uses its locus list, coordinates, names, products, functional categories and promoters, and cites it below.</li>
      </ul>
      {meta ? (
        <table className="about-table">
          <thead><tr><th>Source</th><th>Version</th><th>Licence</th><th>Retrieved</th></tr></thead>
          <tbody>
            {meta.sources.map((s) => (
              <tr key={s.name + s.version}><td>{s.name}</td><td>{s.version}</td><td>{s.licence}</td><td>{s.retrieved}</td></tr>
            ))}
          </tbody>
        </table>
      ) : <p className="faint">Loading the store's sources…</p>}
      <h3>Please cite</h3>
      <ul>
        {CITATIONS.map((c) => (
          <li key={c.doi}><span className="faint">{c.source}:</span> {c.cite} <a href={`https://doi.org/${c.doi}`} target="_blank" rel="noreferrer">doi:{c.doi}</a></li>
        ))}
        <li>The databases (UniProt, ChEMBL, PubChem, RCSB PDB, AlphaFold DB, STRING, the WHO catalogue, ClinicalTrials.gov, NCBI RefSeq) each ask to be cited as described on their own sites.</li>
      </ul>
      <p>The atlas's own code is MIT-licensed: <a href={REPO} target="_blank" rel="noreferrer">{REPO.replace("https://", "")}</a>.</p>
    </>
  );
}

function Privacy({ meta }: { meta: Meta | null }) {
  const operator = meta?.site.operator ?? "the operator of this site";
  const contact = meta?.site.contact;
  return (
    <>
      <h2>Privacy &amp; cookies</h2>
      <p>This instance is run by {operator}.{contact && <> Questions about it: <a href={`mailto:${contact}`}>{contact}</a>.</>}</p>
      <h3>Cookies and browser storage</h3>
      <table className="about-table">
        <thead><tr><th>What</th><th>Set when</th><th>Why</th></tr></thead>
        <tbody>
          <tr><td><code>atlas_session</code> cookie</td><td>you sign in with ORCID</td><td>keeps you signed in for 30 days; holds your ORCID iD and nothing else</td></tr>
          <tr><td><code>atlas_oauth_state</code> cookie</td><td>during sign-in, for 10 minutes</td><td>protects the sign-in from forgery</td></tr>
          <tr><td>browser storage: table preferences</td><td>you change a table's columns</td><td>remembers your columns</td></tr>
          <tr><td>browser storage: notice</td><td>you dismiss the notice</td><td>does not show it again</td></tr>
        </tbody>
      </table>
      <p>There are no analytics, advertising or tracking cookies. The cookies above are strictly necessary for something you asked for, so the site does not ask for consent.</p>
      <h3>What is sent where</h3>
      <ul>
        <li><strong>Questions</strong> typed into “Ask the atlas” are sent to Anthropic to be answered. The atlas does not log them.</li>
        <li><strong>Cloudflare Turnstile</strong> checks that an anonymous asker is human. It loads (challenges.cloudflare.com) only when you first click into the Ask box, and receives signals from your browser. Cloudflare's check may set its own cookies when it loads.</li>
        <li><strong>ORCID</strong> handles sign-in. The atlas receives and keeps only your ORCID iD: not your name, email or record, and it can never write to your record.</li>
        <li><strong>RCSB PDB</strong> (models.rcsb.org): when you open an experimental structure, the viewer loads its coordinate file directly in your browser.</li>
        <li><strong>AlphaFold DB</strong> (alphafold.ebi.ac.uk, run by EMBL-EBI): when you open a predicted structure, the viewer loads the model file directly in your browser.</li>
        <li><strong>The web server</strong> records each request (address, path, time) in the operator's server logs.</li>
      </ul>
      <h3>Counting questions</h3>
      <p>To enforce the question allowance the atlas stores, per question, the time and either your ORCID iD or a keyed hash of your IP address. The IP address itself is never stored, and every row is deleted after 24 hours.</p>
    </>
  );
}

function Terms() {
  return (
    <>
      <h2>Terms &amp; disclaimer</h2>
      <ul>
        <li>The atlas is for research use. It is not medical or clinical advice.</li>
        <li>It is provided as is, without warranty of any kind, and its sources are summarised as published; errors in a source are errors here.</li>
        <li><strong>An absent record is a statement about the public record, not about the biology.</strong> “No ligands” means no public deposit reaches this gene, not that none exists.</li>
        <li>Answers from “Ask the atlas” are generated by a language model from queries over the store. They can be wrong: check them against the rows they cite.</li>
        <li>Each source's licence applies to its data; see <Link to="/about/sources">Sources &amp; licences</Link>.</li>
      </ul>
    </>
  );
}

export function AboutPage({ page, meta }: { page: string | null; meta: Meta | null }) {
  return (
    <article className="about">
      {page === "privacy" ? <Privacy meta={meta} /> : page === "terms" ? <Terms /> : <Sources meta={meta} />}
    </article>
  );
}

export function SiteFooter({ meta }: { meta: Meta | null }) {
  return (
    <footer className="sitefooter">
      <Link to="/about/sources">Sources &amp; licences</Link>
      <Link to="/about/privacy">Privacy &amp; cookies</Link>
      <Link to="/about/terms">Terms &amp; disclaimer</Link>
      {meta?.site.footer_links.map((l) => <a key={l.url} href={l.url} target="_blank" rel="noreferrer">{l.label}</a>)}
      <span className="faint">Code MIT · <a href={REPO} target="_blank" rel="noreferrer">source</a></span>
    </footer>
  );
}

function dismissed(): boolean {
  try { return localStorage.getItem(NOTICE_KEY) === "1"; } catch { return false; }
}

/** Information, not a consent gate: the site behaves the same either way. */
export function SiteNotice() {
  const [hidden, setHidden] = useState(dismissed);
  if (hidden) return null;
  return (
    <div className="sitenotice" role="note">
      <span>The atlas sets no cookies unless you sign in with ORCID, and has no analytics. Asking a question sends it to Anthropic, and anonymous questions are checked by Cloudflare.</span>
      <Link to="/about/privacy">Privacy &amp; cookies</Link>
      <button type="button" className="iconbtn" onClick={() => { try { localStorage.setItem(NOTICE_KEY, "1"); } catch { /* blocked: it just comes back */ } setHidden(true); }}>OK</button>
    </div>
  );
}
