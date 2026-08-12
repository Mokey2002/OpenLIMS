import {
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Filler,
  Legend,
  LinearScale,
  LineElement,
  PointElement,
  Title,
  Tooltip,
} from "chart.js";
import { Bar, Line, Scatter } from "react-chartjs-2";

ChartJS.register(
  BarElement,
  CategoryScale,
  Filler,
  Legend,
  LinearScale,
  LineElement,
  PointElement,
  Title,
  Tooltip
);

const COLORS = [
  "#2563eb",
  "#16a34a",
  "#dc2626",
  "#9333ea",
  "#ea580c",
  "#0891b2",
  "#4f46e5",
  "#be123c",
  "#65a30d",
  "#0f766e",
];

function numericValue(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function buildChartData(chart) {
  const rows = chart.data || [];
  const series = chart.series || [];
  const xKey = chart.xKey;

  if (chart.chartType === "scatter") {
    return {
      datasets: series.map((item, index) => ({
        label: item.label || item.dataKey,
        data: rows
          .map((row) => ({
            x: numericValue(row[xKey]),
            y: numericValue(row[item.dataKey]),
            label: row.sample || row.label || row.entity || "Record",
          }))
          .filter((point) => point.x !== null && point.y !== null),
        backgroundColor: COLORS[index % COLORS.length],
        borderColor: COLORS[index % COLORS.length],
        pointRadius: 5,
        pointHoverRadius: 7,
      })),
    };
  }

  return {
    labels: rows.map((row) => row[xKey]),
    datasets: series.map((item, index) => ({
      label: item.label || item.dataKey,
      data: rows.map((row) => numericValue(row[item.dataKey])),
      backgroundColor:
        chart.chartType === "line"
          ? `${COLORS[index % COLORS.length]}22`
          : COLORS[index % COLORS.length],
      borderColor: COLORS[index % COLORS.length],
      borderWidth: chart.chartType === "line" ? 2 : 1,
      fill: chart.chartType === "line" && series.length === 1,
      tension: 0.24,
      spanGaps: true,
      pointRadius: chart.chartType === "line" ? 3 : undefined,
      pointHoverRadius: chart.chartType === "line" ? 5 : undefined,
    })),
  };
}

function buildOptions(chart) {
  const stacked = Boolean(chart.stacked);
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: {
      mode: "nearest",
      intersect: false,
    },
    plugins: {
      legend: {
        display: (chart.series || []).length > 1,
        position: "bottom",
        labels: {
          boxWidth: 12,
          usePointStyle: true,
        },
      },
      tooltip: {
        callbacks: {
          label(context) {
            const raw = context.raw;
            if (raw && typeof raw === "object" && "label" in raw) {
              return `${raw.label}: ${context.dataset.label} ${raw.y}`;
            }
            return `${context.dataset.label}: ${context.formattedValue}`;
          },
        },
      },
    },
    scales: {
      x: {
        stacked,
        title: {
          display: Boolean(chart.xAxisLabel),
          text: chart.xAxisLabel,
        },
        ticks: {
          maxRotation: 45,
          minRotation: 0,
          autoSkip: true,
          maxTicksLimit: 20,
        },
      },
      y: {
        stacked,
        beginAtZero: chart.chartType !== "scatter",
        title: {
          display: Boolean(chart.series?.[0]?.axisLabel),
          text: chart.series?.[0]?.axisLabel || "Value",
        },
      },
    },
  };
}

export default function AssistantChart({ chart }) {
  if (
    !chart ||
    !chart.chartType ||
    !Array.isArray(chart.data) ||
    !Array.isArray(chart.series)
  ) {
    return null;
  }

  const data = buildChartData(chart);
  const options = buildOptions(chart);

  return (
    <div className="assistant-chart-card">
      <div className="assistant-chart-title">{chart.meta?.title || "Chart"}</div>

      {chart.meta?.description && (
        <div className="assistant-chart-description">
          {chart.meta.description}
        </div>
      )}

      <div className="assistant-chart-canvas">
        {chart.chartType === "bar" && <Bar data={data} options={options} />}
        {chart.chartType === "line" && <Line data={data} options={options} />}
        {chart.chartType === "scatter" && (
          <Scatter data={data} options={options} />
        )}
      </div>
    </div>
  );
}
