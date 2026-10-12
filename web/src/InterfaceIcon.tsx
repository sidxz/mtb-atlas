/** Small, consistent outline icons for workspace controls. */
export function InterfaceIcon({ name }: { name: "search" | "genome" | "targets" | "screens" | "profiling" | "clinical" | "theme" | "expand" | "collapse" | "filter" | "ask" | "columns" | "format" }) {
  const paths = {
    // Narrowing rings: a cohort reduced by successive criteria.
    targets: <><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="4.5" /><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" /></>,
    screens: <><rect x="3" y="4" width="18" height="16" rx="2" />{[7, 12, 17].flatMap(x => [8, 12, 16].map(y => <circle key={`${x}-${y}`} cx={x} cy={y} r="0.8" fill="currentColor" stroke="none" />))}</>,
    profiling: <><path d="m5 3 6 3v6l-6 3-3-2M5 3 2 5M11 6l4-2" /><circle cx="15" cy="15" r="5" /><path d="m19 19 3 3M12 15h6M15 12v6" /></>,
    columns: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16M15 4v16" /></>,
    format: <><path d="m8 3 10 10-7 7a3 3 0 0 1-4 0L2 15a3 3 0 0 1 0-4l7-7M3 14h14M7 2l5 5" /><path d="M20 16s-2 2.5-2 4a2 2 0 0 0 4 0c0-1.5-2-4-2-4Z" /></>,
    search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4.5 4.5" /></>,
    genome: <><path d="M7 3c0 8 10 10 10 18M17 3C17 11 7 13 7 21M8 5h8M9 9h6M9 15h6M8 19h8" /></>,
    clinical: <><path d="m9 5 10 10a5 5 0 0 1-7 7L2 12a5 5 0 0 1 7-7Z" transform="translate(2 -2)" /><path d="m9 15 7-7" /></>,
    theme: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" /></>,
    expand: <path d="M14 4h6v6m0-6-7 7M10 20H4v-6m0 6 7-7" />,
    collapse: <path d="M20 4 13 11m0-6v6h6M4 20l7-7m-6 0h6v6" />,
    filter: <><path d="M4 6h16M7 12h10M10 18h4" /></>,
    ask: <><path d="M20 11.5a8 8 0 0 1-8 8H5l-3 2V12a9 9 0 0 1 18-.5Z" /><path d="M7 10h8M7 14h5" /></>,
  };
  return <svg className="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}
