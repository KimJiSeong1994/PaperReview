/**
 * Plotly lightweight wrapper — plotly.js-basic-dist-min (~1.5MB vs ~4.7MB full)
 * Supports: scatter, bar, pie, scatterpolar (covers all project chart types)
 */
import createPlotlyComponent from 'react-plotly.js/factory';
import Plotly from 'plotly.js-basic-dist-min';

const Plot = createPlotlyComponent(Plotly);
export default Plot;
export type { Data, Layout } from 'plotly.js';
