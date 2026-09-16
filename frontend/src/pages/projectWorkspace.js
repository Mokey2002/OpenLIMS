export function filterProjectSamples(samples, query) {
  const normalized = query.trim().toLowerCase();
  return samples.filter(sample => [sample.sample_id, sample.status, sample.container_code]
    .some(value => String(value || "").toLowerCase().includes(normalized)));
}
