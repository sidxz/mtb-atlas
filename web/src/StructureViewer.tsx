/**
 * Mol* viewer: structure, its ligands, and the resistance residues drawn on it.
 *
 * This is the reason the frontend is a real build rather than a single page.
 * Mol*'s prebuilt CDN bundle exports only its `Viewer` wrapper, so per-residue
 * selection is unreachable from a CDN-only page; imported from npm, the
 * selection language is available and a resistance residue can become its own
 * component with its own representation.
 */

import { useEffect, useRef, useState } from "react";
import { createPluginUI } from "molstar/lib/mol-plugin-ui";
import { renderReact18 } from "molstar/lib/mol-plugin-ui/react18";
import { DefaultPluginUISpec } from "molstar/lib/mol-plugin-ui/spec";
import type { PluginUIContext } from "molstar/lib/mol-plugin-ui/context";
import { MolScriptBuilder as MS } from "molstar/lib/mol-script/language/builder";
import { Script } from "molstar/lib/mol-script/script";
import { StructureSelection } from "molstar/lib/mol-model/structure";
import { Loci } from "molstar/lib/mol-model/loci";
import { PLDDTConfidenceColorThemeProvider } from "molstar/lib/extensions/model-archive/quality-assessment/color/plddt";
import { Color } from "molstar/lib/mol-util/color";
import "molstar/build/viewer/molstar.css";

import type { Variant } from "./api";

const themeColour = (name: string, fallback: number) => {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const parsed = Number.parseInt(raw.replace("#", ""), 16);
  return Color(Number.isNaN(parsed) ? fallback : parsed);
};

const PROTEIN = Color(0x5b7fb5);
const LIGAND = Color(0x2fae99);
const RESISTANCE = Color(0xe0218a);

export interface ViewerSource {
  /** PDB id, or an AlphaFold entry id. */
  id: string;
  url: string;
  format: "mmcif" | "pdb";
  binary: boolean;
  predicted: boolean;
  label: string;
}

export function pdbSource(pdbId: string, title: string | null): ViewerSource {
  return {
    id: pdbId,
    // BinaryCIF: a few hundred KB where mmCIF is megabytes.
    url: `https://models.rcsb.org/${pdbId.toLowerCase()}.bcif`,
    format: "mmcif",
    binary: true,
    predicted: false,
    label: title ?? pdbId,
  };
}

export function alphafoldSource(cifUrl: string, entryId: string): ViewerSource {
  return {
    id: entryId,
    url: cifUrl,
    format: "mmcif",
    binary: false,
    predicted: true,
    label: "AlphaFold prediction",
  };
}

interface Props {
  source: ViewerSource | null;
  /** WHO-graded variants; only the ones with a residue position can be drawn. */
  variants: Variant[];
  showLigands: boolean;
  showResistance: boolean;
  focusResidue: number | null;
}

export function StructureViewer({
  source,
  variants,
  showLigands,
  showResistance,
  focusResidue,
}: Props) {
  const host = useRef<HTMLDivElement | null>(null);
  const plugin = useRef<PluginUIContext | null>(null);
  const [status, setStatus] = useState<string | null>("Starting viewer…");
  // The plugin is created asynchronously. Without this the load effect runs
  // once against a null plugin and never again, and the stage stays empty.
  const [ready, setReady] = useState(false);

  // One plugin for the life of the component; structures are swapped inside it.
  useEffect(() => {
    let disposed = false;
    // StrictMode mounts effects twice. Mol* calls createRoot on the target, and
    // React refuses a second createRoot on the same node, so give each mount a
    // throwaway child container rather than the host itself.
    const container = document.createElement("div");
    container.style.cssText = "position:absolute;inset:0";
    host.current?.appendChild(container);

    (async () => {
      const spec = DefaultPluginUISpec();
      spec.layout = { initial: { isExpanded: false, showControls: false } };
      // Set at creation: canvas3d does not exist yet to be configured after.
      spec.canvas3d = { renderer: { backgroundColor: themeColour("--viewer-bg", 0x10151f) } };
      const created = await createPluginUI({
        target: container,
        spec,
        render: renderReact18,
      });
      // Not registered by the default spec, and it is the whole point of
      // showing a predicted model: a low-pLDDT loop must not read as resolved.
      if (!created.representation.structure.themes.colorThemeRegistry.has(
        PLDDTConfidenceColorThemeProvider,
      )) {
        created.representation.structure.themes.colorThemeRegistry.add(
          PLDDTConfidenceColorThemeProvider,
        );
      }
      if (disposed) {
        created.dispose();
        return;
      }
      plugin.current = created;
      // A handle for debugging the viewer from the console; harmless in production.
      (window as unknown as { molstar?: PluginUIContext }).molstar = created;
      setReady(true);
      setStatus(null);
    })().catch((error: unknown) => setStatus(`Viewer failed to start: ${String(error)}`));
    return () => {
      disposed = true;
      plugin.current?.dispose();
      plugin.current = null;
      container.remove();
    };
  }, []);

  useEffect(() => {
    const context = plugin.current;
    if (!ready || !context || !source) return;
    let cancelled = false;

    (async () => {
      setStatus(`Loading ${source.id}…`);
      await context.clear();

      const data = await context.builders.data.download(
        { url: source.url, isBinary: source.binary },
        { state: { isGhost: true } },
      );
      const trajectory = await context.builders.structure.parseTrajectory(data, source.format);
      const model = await context.builders.structure.createModel(trajectory);
      const structure = await context.builders.structure.createStructure(model);
      if (cancelled) return;

      const polymer = await context.builders.structure.tryCreateComponentStatic(
        structure,
        "polymer",
      );
      if (polymer) {
        await context.builders.structure.representation.addRepresentation(polymer, {
          type: "cartoon",
          // A predicted model is coloured by its own confidence, so a low-pLDDT
          // loop never reads as though it were resolved.
          color: (source.predicted ? "plddt-confidence" : "uniform") as "uniform",
          colorParams: source.predicted ? undefined : { value: PROTEIN },
        });
      }

      if (showLigands) {
        const ligand = await context.builders.structure.tryCreateComponentStatic(
          structure,
          "ligand",
        );
        if (ligand) {
          await context.builders.structure.representation.addRepresentation(ligand, {
            type: "ball-and-stick",
            color: "uniform",
            colorParams: { value: LIGAND },
          });
        }
      }

      const positions = [
        ...new Set(
          variants
            .filter((v) => v.residue_position !== null)
            .map((v) => v.residue_position as number),
        ),
      ];
      if (showResistance && positions.length && !source.predicted) {
        const expression = MS.struct.generator.atomGroups({
          "residue-test": MS.core.set.has([
            MS.set(...positions),
            MS.struct.atomProperty.macromolecular.auth_seq_id(),
          ]),
        });
        const component = await context.builders.structure.tryCreateComponentFromExpression(
          structure,
          expression,
          "resistance-residues",
          { label: "WHO-graded resistance residues" },
        );
        if (component) {
          await context.builders.structure.representation.addRepresentation(component, {
            type: "ball-and-stick",
            color: "uniform",
            colorParams: { value: RESISTANCE },
          });
        }
      }

      // The builder path does not move the camera; only the preset helpers do.
      // Without this the structure loads correctly and sits off-screen.
      context.managers.camera.reset();
      context.canvas3d?.requestCameraReset();
      if (!cancelled) setStatus(null);
    })().catch((error: unknown) => {
      if (!cancelled) setStatus(`Could not load ${source.id}: ${String(error)}`);
    });

    return () => {
      cancelled = true;
    };
  }, [ready, source, variants, showLigands, showResistance]);

  // Follow the page's theme: Mol* paints its own background and would
  // otherwise stay light inside a dark page.
  useEffect(() => {
    const apply = () =>
      plugin.current?.canvas3d?.setProps({
        renderer: { backgroundColor: themeColour("--viewer-bg", 0x10151f) },
      });
    apply();
    const observer = new MutationObserver(apply);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", apply);
    return () => {
      observer.disconnect();
      media.removeEventListener("change", apply);
    };
  }, [ready]);

  // Clicking a variant in the table swings the camera onto that residue.
  useEffect(() => {
    const context = plugin.current;
    if (!ready || !context || focusResidue === null) return;
    const data = context.managers.structure.hierarchy.current.structures[0]?.cell.obj?.data;
    if (!data) return;
    const selection = Script.getStructureSelection(
      (Q) =>
        Q.struct.generator.atomGroups({
          "residue-test": Q.core.rel.eq([
            Q.struct.atomProperty.macromolecular.auth_seq_id(),
            focusResidue,
          ]),
        }),
      data,
    );
    const loci = StructureSelection.toLociWithSourceUnits(selection);
    if (Loci.isEmpty(loci)) return;
    context.managers.camera.focusLoci(loci);
    context.managers.interactivity.lociHighlights.highlightOnly({ loci });
  }, [ready, focusResidue]);

  return (
    <div className="stage">
      <div ref={host} />
      {status && <div className="stageover">{status}</div>}
    </div>
  );
}
