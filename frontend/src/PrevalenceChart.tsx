import {
  Bar,
  BarChart,
  CartesianGrid,
  ErrorBar,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";

export interface PrevalenceChartItem {
  county: string;
  prevalence: number;
  confidence: [number, number];
}

export default function PrevalenceChart({ data }: { data: PrevalenceChartItem[] }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart
        data={data}
        layout="vertical"
        margin={{ top: 8, right: 24, bottom: 0, left: 8 }}
      >
        <CartesianGrid horizontal={false} stroke="#dfe4dc" strokeDasharray="3 5" />
        <XAxis
          axisLine={false}
          domain={[0, "dataMax + 5"]}
          tick={{ fill: "#687169", fontSize: 12 }}
          tickFormatter={(value: number) => `${value}%`}
          tickLine={false}
          type="number"
        />
        <YAxis
          axisLine={false}
          dataKey="county"
          tick={{ fill: "#26332b", fontSize: 12 }}
          tickLine={false}
          type="category"
          width={96}
        />
        <Bar dataKey="prevalence" fill="#d56742" radius={[0, 6, 6, 0]}>
          <ErrorBar dataKey="confidence" direction="x" stroke="#243c31" width={5} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
