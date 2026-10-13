/**
 * What a public site owes its visitors: whose data this is, what is stored and
 * sent where, and what the atlas does not promise. Written so any operator can
 * run it unchanged; who runs this instance comes from /meta.
 */
import { useState } from "react";
import { Link } from "react-router";
import type { Meta } from "./api";
import { questionDestination } from "./askAccess";

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
      <p>The atlas brings together public data on <i>M. tuberculosis</i> genes, experiments, compounds, drugs and clinical trials. It also calculates summaries and links records across these sources.</p>
      <p>The table below lists the source versions used in this atlas and their retrieval dates. Newer records may be available from the original databases.</p>
      <h3>Reusing the data</h3>
      <p>Each source has its own licence. Check the terms for the data you plan to reuse.</p>
      <ul>
        <li><strong>ChEMBL:</strong> bioactivity records, drug mechanisms and data derived from ChEMBL are shared under <strong>CC BY-SA 3.0</strong>.</li>
        <li><strong>ClinicalTrials.gov:</strong> trial records reflect the retrieval date below. Their inclusion does not imply endorsement by the U.S. National Library of Medicine.</li>
        <li><strong>PubChem:</strong> reuse terms depend on the depositor. Check the original assay record for the screening data you use.</li>
        <li><strong>Mycobrowser:</strong> the source does not state a licence for the gene annotations used here. The citation below identifies that work; it does not grant permission to reuse it.</li>
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
      ) : <p className="faint">Loading source versions and retrieval dates…</p>}
      <h3>Citing the research</h3>
      <p>Cite the original studies and databases for the evidence you use. These studies supply the atlas’s gene annotations, essentiality and fitness data:</p>
      <ul>
        {CITATIONS.map((c) => (
          <li key={c.doi}><span className="faint">{c.source}:</span> {c.cite} <a href={`https://doi.org/${c.doi}`} target="_blank" rel="noreferrer">doi:{c.doi}</a></li>
        ))}
      </ul>
      <p>For UniProt, ChEMBL, PubChem, RCSB PDB, AlphaFold DB, STRING, the WHO catalogue, ClinicalTrials.gov and NCBI RefSeq, follow the citation guidance on the source’s website. Include the release or retrieval date where relevant.</p>
      <h3>Source code</h3>
      <p>The atlas software is available under the MIT licence. The data licences listed above apply separately. <a href={REPO} target="_blank" rel="noreferrer">View the code on GitHub</a>.</p>
    </>
  );
}

function Privacy({ meta }: { meta: Meta | null }) {
  const operator = meta?.site.operator;
  const contact = meta?.site.contact;
  return (
    <>
      <h2>Privacy &amp; cookies</h2>
      <p>You can browse the atlas without an account. Asking a question uses a language model service; ORCID sign-in is optional.</p>
      {(operator || contact) && <p>{operator && <>This site is operated by {operator}. </>}{contact && <>For questions about privacy, contact <a href={`mailto:${contact}`}>{contact}</a>.</>}</p>}
      <h3>Cookies and browser storage</h3>
      <table className="about-table about-storage-table">
        <thead><tr><th>What</th><th>Set when</th><th>Why</th></tr></thead>
        <tbody>
          <tr><td>Sign-in cookie<br /><code>atlas_session</code></td><td>After ORCID sign-in; expires after 30 days</td><td>Keeps you signed in using your ORCID iD, an expiry time and a signature that prevents tampering.</td></tr>
          <tr><td>Sign-in check<br /><code>atlas_oauth_state</code></td><td>When you start sign-in; expires after 10 minutes</td><td>Checks that the response from ORCID belongs to the sign-in you started and remembers which page to return to.</td></tr>
          <tr><td>Table preferences</td><td>When you change columns or formatting</td><td>Saves your table settings in this browser until you clear the site’s browser storage.</td></tr>
          <tr><td>Privacy notice preference</td><td>When you dismiss the notice</td><td>Remembers your choice in this browser until you clear the site’s browser storage.</td></tr>
        </tbody>
      </table>
      <p>The atlas does not use analytics or advertising cookies. Signing out removes the session cookie. You can remove saved preferences through your browser’s site-data settings.</p>
      <h3>Questions and sign-in</h3>
      <ul>
        <li><strong>Ask the atlas:</strong> when you submit a question, its text and the data retrieved to answer it are sent to {questionDestination(meta)}{meta?.site.llm ? <> (model: <code>{meta.site.llm.model}</code>)</> : null}. The atlas application does not save question text or answers in its usage records or application logs. The model service’s own data-handling terms apply to what it receives.</li>
        <li><strong>Cloudflare Turnstile:</strong> when enabled, this checks anonymous question requests for automated traffic. It loads when you focus the Ask field and receives browser signals; the atlas also sends your IP address when verifying the check. Cloudflare may set cookies as part of this check. Signed-in users do not need it.</li>
        <li><strong>ORCID:</strong> the atlas requests permission to verify your ORCID iD. It keeps that iD and discards the name and access token returned during sign-in. It does not request permission to edit your ORCID record.</li>
      </ul>
      <h3>Question limits and server logs</h3>
      <p>When question limits are enabled, the atlas records the time of each accepted question with either your ORCID iD or a keyed hash of your IP address. The usage database does not store your raw IP address or question text. Records older than 24 hours are removed the next time usage is checked.</p>
      <p>Server access logs are separate from these usage records. Depending on the hosting configuration, they may contain IP addresses, requested URLs and request times. Their retention is controlled by the site operator.</p>
      <h3>Structure viewers</h3>
      <p>Opening a protein structure loads its coordinate file directly from RCSB PDB (models.rcsb.org) or AlphaFold DB (alphafold.ebi.ac.uk). Your browser connects to that service to download the file.</p>
    </>
  );
}

function Terms() {
  return (
    <>
      <h2>Terms &amp; disclaimer</h2>
      <p>The atlas is a research tool for exploring public evidence about <i>M. tuberculosis</i>. It does not provide medical advice or treatment recommendations.</p>
      <h3>Interpreting the evidence</h3>
      <p>Records reflect the source versions listed on <Link to="/about/sources">Sources &amp; licences</Link>. Coverage is incomplete, and errors can occur in the original data, in links between records or in the atlas’s summaries. Check the original experiment or database record before relying on a result.</p>
      <p>A missing record means the atlas has no matching evidence in the data it includes. For example, “No ligands” means no ligand record is linked to that gene here. It does not establish that the protein cannot bind a compound.</p>
      <h3>Answers from Ask the atlas</h3>
      <p>Answers are generated by a language model using queries against the atlas data. The model can misread results, omit qualifications or draw an unsupported conclusion. Follow the linked records and check the evidence before using an answer in your work.</p>
      <h3>Reuse and availability</h3>
      <p>The atlas is provided “as is”, without warranty of any kind. Accuracy, completeness and continued availability are not guaranteed.</p>
      <p>Source data remains subject to its original licence. The atlas software is released under the MIT licence. See <Link to="/about/sources">Sources &amp; licences</Link> for attribution and reuse information.</p>
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
      <span className="faint"><a href={REPO} target="_blank" rel="noreferrer">Source code</a></span>
      <a href={`${REPO}/issues`} target="_blank" rel="noreferrer">Report bugs</a>
    </footer>
  );
}

function dismissed(): boolean {
  try { return localStorage.getItem(NOTICE_KEY) === "1"; } catch { return false; }
}

/** Information, not a consent gate: the site behaves the same either way. */
export function SiteNotice({ meta }: { meta: Meta | null }) {
  const [hidden, setHidden] = useState(dismissed);
  if (hidden) return null;
  return (
    <div className="sitenotice" role="note">
      <span>Questions you submit are sent to {questionDestination(meta)}. Anonymous questions may require a Cloudflare check. ORCID sign-in uses cookies to keep you signed in.</span>
      <Link to="/about/privacy">Privacy &amp; cookies</Link>
      <button type="button" className="iconbtn" onClick={() => { try { localStorage.setItem(NOTICE_KEY, "1"); } catch { /* blocked: it just comes back */ } setHidden(true); }}>Dismiss</button>
    </div>
  );
}
