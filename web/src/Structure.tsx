/**
 * Depictions, drawn in the browser from the SMILES the API already serves.
 *
 * Nothing is added to the store or the pipeline: a depiction is a rendering of
 * a SMILES, not a fact about the molecule, so it belongs in the presentation
 * layer. The frontend still reads only the API.
 *
 * RDKit rather than a lighter drawer because TB chemistry is full of the cases
 * lighter drawers lay out badly -- the rifamycins are ansamycin macrocycles,
 * and benzothiazinones, nitroimidazoles and bedaquiline's quinoline are fused
 * systems. A table of 132 compounds exists so scaffolds can be recognised at a
 * glance, and a bad layout defeats the entire point of showing them.
 *
 * It costs 7.4 MB of WebAssembly, so it is fetched on first use and never by
 * anyone who does not open a chemistry tab, and each row waits until it
 * scrolls near the viewport.
 */

import { useEffect, useRef, useState } from "react";
// The package's `exports` map allows only these two specifiers; `?url` keeps
// the 7.4 MB out of the bundle and lets Vite emit both as hashed assets.
import rdkitScript from "@rdkit/rdkit?url";
import rdkitWasm from "@rdkit/rdkit/RDKit_minimal.wasm?url";

interface Mol {
  is_valid: () => boolean;
  get_svg: (width: number, height: number) => string;
  delete: () => void;
}
interface RDKit {
  get_mol: (smiles: string) => Mol | null;
}

let pending: Promise<RDKit> | null = null;

/** Load the WebAssembly once per page, on first depiction. */
function rdkit(): Promise<RDKit> {
  if (pending) return pending;
  pending = new Promise<RDKit>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = rdkitScript;
    script.onload = () => {
      const init = (window as unknown as { initRDKitModule?: (o: object) => Promise<RDKit> })
        .initRDKitModule;
      if (!init) {
        reject(new Error("RDKit loaded without initRDKitModule"));
        return;
      }
      // Vite emits the .wasm as a hashed asset, so the loader has to be told
      // where it went rather than guessing a sibling path.
      init({ locateFile: () => rdkitWasm }).then(resolve, reject);
    };
    script.onerror = () => reject(new Error("could not load the structure renderer"));
    document.head.appendChild(script);
  });
  return pending;
}

/**
 * One depiction, on white because that is the convention and because it keeps
 * the drawing legible under either theme without recolouring bonds.
 *
 * Rendered into an `<img>` via a data URI rather than injected as markup: an
 * SVG in an `<img>` cannot execute script, so nothing downstream of ChEMBL's
 * SMILES ever becomes live DOM.
 */
export function Structure({
  smiles,
  width = 176,
  height = 94,
  title,
}: {
  smiles: string | null | undefined;
  width?: number;
  height?: number;
  title?: string;
}) {
  const box = useRef<HTMLDivElement | null>(null);
  const [near, setNear] = useState(false);
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  // 132 molecules at once is a visible stall; a dozen is not.
  useEffect(() => {
    const element = box.current;
    if (!element || near) return;
    const observer = new IntersectionObserver(
      ([entry]) => entry.isIntersecting && setNear(true),
      { rootMargin: "300px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [near]);

  useEffect(() => {
    if (!near || !smiles) return;
    let cancelled = false;
    rdkit()
      .then((library) => {
        if (cancelled) return;
        const mol = library.get_mol(smiles);
        try {
          if (!mol || !mol.is_valid()) setFailed(true);
          else setSvg(mol.get_svg(width, height));
        } finally {
          // WebAssembly memory is not garbage collected: a molecule that is
          // not deleted leaks, and this table draws hundreds.
          mol?.delete();
        }
      })
      .catch(() => setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [near, smiles, width, height]);

  return (
    <div className="struct" ref={box} style={{ width, height }} title={title}>
      {svg ? (
        <img
          src={`data:image/svg+xml;utf8,${encodeURIComponent(svg)}`}
          alt={title ? `Structure of ${title}` : "Chemical structure"}
          width={width}
          height={height}
        />
      ) : (
        <span className="faint">{!smiles ? "no SMILES" : failed ? "unparsed" : ""}</span>
      )}
    </div>
  );
}

/** Out to ChEMBL's own record, so a number can be chased to its source.
 *
 * `/explore/` is the live path; the older `*_report_card/` URLs 301 to it.
 * Click is stopped from bubbling, because the row underneath opens the
 * compound panel and a link that also navigates the page is a trap.
 */
export function ChemblLink({
  kind,
  id,
  label,
}: {
  kind: "compound" | "assay" | "document";
  id: string;
  label?: string;
}) {
  return (
    <a
      className="chembl"
      href={`https://www.ebi.ac.uk/chembl/explore/${kind}/${id}`}
      target="_blank"
      rel="noreferrer"
      onClick={(event) => event.stopPropagation()}
      title={`${id} at ChEMBL`}
    >
      {label ?? id}
    </a>
  );
}
