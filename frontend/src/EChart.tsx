import { useEffect, useRef } from "react";
import { BarChart, LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, MarkLineComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { SVGRenderer } from "echarts/renderers";

echarts.use([BarChart, LineChart, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent, SVGRenderer]);

export type ChartOption = echarts.EChartsCoreOption;

/** Um gráfico do ECharts que acompanha o tamanho do contêiner. */
export function EChart({ option, height = 220, label }: { option: ChartOption; height?: number; label: string }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const chart = echarts.init(host, undefined, { renderer: "svg" });
    chartRef.current = chart;
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(host);
    return () => {
      observer.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(option, { notMerge: true });
  }, [option]);

  return <div ref={hostRef} className="echart" style={{ height }} role="img" aria-label={label} />;
}

/** Cores do tema atual (claro ou escuro), lidas das variáveis CSS. */
export function chartTheme() {
  const css = getComputedStyle(document.documentElement);
  const v = (name: string) => css.getPropertyValue(name).trim();
  return {
    teamA: v("--series-a"),
    teamB: v("--series-b"),
    text: v("--text"),
    muted: v("--muted"),
    grid: v("--border"),
    surface: v("--card"),
  };
}
