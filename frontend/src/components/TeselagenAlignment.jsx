import { useEffect, useRef, useState } from "react";
import { Alert } from "react-bootstrap";

export default function TeselagenAlignment({ records, jobId }) {
  const frame = useRef(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setFailed(true), 20000);
    function receive(event) {
      if (event.origin !== window.location.origin || event.source !== frame.current?.contentWindow) return;
      if (event.data?.type === "openlims-alignment-loaded") {
        clearTimeout(timer);
        setFailed(false);
      } else if (event.data?.type === "openlims-alignment-error") {
        clearTimeout(timer);
        setFailed(true);
      }
    }
    window.addEventListener("message", receive);
    return () => { clearTimeout(timer); window.removeEventListener("message", receive); };
  }, []);
  function load() {
    frame.current?.contentWindow.postMessage({
      type: "openlims-alignment",
      id: `alignment-${jobId}`,
      tracks: records.map((record, index) => ({
        sequenceData: {
          id: `sequence-${jobId}-${index}`, name: record.name,
          sequence: record.sequence.replace(/[-.]/g, ""), circular: false,
        },
        alignmentData: { sequence: record.sequence.replaceAll(".", "-") },
      })),
    }, window.location.origin);
  }
  return <>
    {failed && <Alert variant="warning">The interactive viewer could not load. Use the table view or download FASTA.</Alert>}
    <iframe ref={frame} title="TeselaGen alignment viewer" src="/alignment-viewer.html"
      onLoad={load} style={{ width: "100%", height: "640px", border: 0, scrollMarginTop: "80px" }} />
  </>;
}
