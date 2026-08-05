function numberValue(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatValue(value) {
  const parsed = Number(value);

  if (!Number.isFinite(parsed)) {
    return value;
  }

  if (Math.abs(parsed) >= 1000) {
    return parsed.toLocaleString();
  }

  return Number.isInteger(parsed) ? String(parsed) : parsed.toFixed(2);
}

function getSeries(chart) {
  return chart?.series?.[0] || {};
}

function BarChart({ chart }) {
  const xKey = chart.xKey;
  const series = getSeries(chart);
  const yKey = series.dataKey;
  const data = chart.data || [];
  const maxValue = Math.max(...data.map((row) => numberValue(row[yKey])), 1);

  return (
    <div className="assistant-chart-bars">
      {data.map((row, index) => {
        const value = numberValue(row[yKey]);
        const width = `${Math.max((value / maxValue) * 100, value > 0 ? 4 : 0)}%`;

        return (
          <div className="assistant-chart-bar-row" key={`${row[xKey]}-${index}`}>
            <div className="assistant-chart-bar-label">{row[xKey]}</div>
            <div className="assistant-chart-bar-track">
              <div
                className="assistant-chart-bar-fill"
                style={{ width }}
              />
            </div>
            <div className="assistant-chart-bar-value">{formatValue(value)}</div>
          </div>
        );
      })}
    </div>
  );
}

function LineChart({ chart }) {
  const xKey = chart.xKey;
  const series = getSeries(chart);
  const yKey = series.dataKey;
  const data = chart.data || [];

  const values = data.map((row) => numberValue(row[yKey]));
  const minValue = Math.min(...values, 0);
  const maxValue = Math.max(...values, 1);
  const range = maxValue - minValue || 1;

  const width = 320;
  const height = 160;
  const padLeft = 34;
  const padRight = 12;
  const padTop = 16;
  const padBottom = 30;
  const innerWidth = width - padLeft - padRight;
  const innerHeight = height - padTop - padBottom;

  const points = data.map((row, index) => {
    const x =
      padLeft +
      (data.length <= 1 ? innerWidth / 2 : (index / (data.length - 1)) * innerWidth);
    const y =
      padTop +
      innerHeight -
      ((numberValue(row[yKey]) - minValue) / range) * innerHeight;

    return {
      x,
      y,
      label: row[xKey],
      value: numberValue(row[yKey]),
    };
  });

  const polyline = points.map((point) => `${point.x},${point.y}`).join(" ");

  return (
    <svg
      className="assistant-chart-svg"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={chart.meta?.title || "Line chart"}
    >
      <line x1={padLeft} y1={padTop} x2={padLeft} y2={padTop + innerHeight} />
      <line
        x1={padLeft}
        y1={padTop + innerHeight}
        x2={padLeft + innerWidth}
        y2={padTop + innerHeight}
      />

      <text x={4} y={padTop + 4}>{formatValue(maxValue)}</text>
      <text x={4} y={padTop + innerHeight}>{formatValue(minValue)}</text>

      {points.length > 1 && <polyline points={polyline} />}

      {points.map((point, index) => (
        <g key={`${point.label}-${index}`}>
          <circle cx={point.x} cy={point.y} r="3.5">
            <title>{`${point.label}: ${formatValue(point.value)}`}</title>
          </circle>
        </g>
      ))}

      {points.length > 0 && (
        <>
          <text x={padLeft} y={height - 8}>
            {points[0].label}
          </text>
          <text x={padLeft + innerWidth - 52} y={height - 8}>
            {points[points.length - 1].label}
          </text>
        </>
      )}
    </svg>
  );
}

function ScatterChart({ chart }) {
  const xKey = chart.xKey;
  const series = getSeries(chart);
  const yKey = series.dataKey;
  const data = chart.data || [];

  const xValues = data.map((row) => numberValue(row[xKey]));
  const yValues = data.map((row) => numberValue(row[yKey]));

  const minX = Math.min(...xValues, 0);
  const maxX = Math.max(...xValues, 1);
  const minY = Math.min(...yValues, 0);
  const maxY = Math.max(...yValues, 1);

  const rangeX = maxX - minX || 1;
  const rangeY = maxY - minY || 1;

  const width = 320;
  const height = 170;
  const padLeft = 38;
  const padRight = 14;
  const padTop = 16;
  const padBottom = 34;
  const innerWidth = width - padLeft - padRight;
  const innerHeight = height - padTop - padBottom;

  const points = data.map((row) => {
    const xValue = numberValue(row[xKey]);
    const yValue = numberValue(row[yKey]);

    return {
      label: row.sample || row.label || "Sample",
      xValue,
      yValue,
      x: padLeft + ((xValue - minX) / rangeX) * innerWidth,
      y: padTop + innerHeight - ((yValue - minY) / rangeY) * innerHeight,
    };
  });

  return (
    <svg
      className="assistant-chart-svg"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={chart.meta?.title || "Scatter chart"}
    >
      <line x1={padLeft} y1={padTop} x2={padLeft} y2={padTop + innerHeight} />
      <line
        x1={padLeft}
        y1={padTop + innerHeight}
        x2={padLeft + innerWidth}
        y2={padTop + innerHeight}
      />

      <text x={4} y={padTop + 4}>{formatValue(maxY)}</text>
      <text x={4} y={padTop + innerHeight}>{formatValue(minY)}</text>
      <text x={padLeft} y={height - 10}>{formatValue(minX)}</text>
      <text x={padLeft + innerWidth - 36} y={height - 10}>{formatValue(maxX)}</text>

      {points.map((point, index) => (
        <circle key={`${point.label}-${index}`} cx={point.x} cy={point.y} r="4">
          <title>
            {`${point.label}: ${chart.xAxisLabel || xKey} ${formatValue(point.xValue)}, ${series.label || yKey} ${formatValue(point.yValue)}`}
          </title>
        </circle>
      ))}
    </svg>
  );
}

export default function AssistantChart({ chart }) {
  if (!chart || !chart.chartType || !Array.isArray(chart.data)) {
    return null;
  }

  return (
    <div className="assistant-chart-card">
      <div className="assistant-chart-title">{chart.meta?.title || "Chart"}</div>

      {chart.meta?.description && (
        <div className="assistant-chart-description">
          {chart.meta.description}
        </div>
      )}

      {chart.chartType === "bar" && <BarChart chart={chart} />}
      {chart.chartType === "line" && <LineChart chart={chart} />}
      {chart.chartType === "scatter" && <ScatterChart chart={chart} />}
    </div>
  );
}
