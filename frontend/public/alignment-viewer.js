/* The isolated viewer receives only the selected alignment, never credentials. */
window.addEventListener('message', event => {
  if (event.source !== window.parent || event.origin !== window.location.origin ||
      event.data?.type !== 'openlims-alignment') return;
  try {
    window.createAlignmentView(document.getElementById('alignment'), {
      id: event.data.id,
      alignmentTracks: event.data.tracks,
      alignmentAnnotationVisibility: { axis: true, sequence: true },
    });
    window.parent.postMessage({ type: 'openlims-alignment-loaded' }, window.location.origin);
  } catch {
    window.parent.postMessage({ type: 'openlims-alignment-error' }, window.location.origin);
  }
});
