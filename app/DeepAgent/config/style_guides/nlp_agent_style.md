# NLP & Agent Domain Style Guide

## Domain-Specific Visual Patterns

### Architecture Diagrams
- Show the typical NLP pipeline: Input → Tokenizer → Encoder → Decoder → Output
- For agent systems: Environment → Observation → Agent → Action → Environment loop
- Use colored boxes for different model components (encoder=blue, decoder=green, attention=orange)
- Include dimension annotations (e.g., "d_model=768", "seq_len=512")

### Attention Visualization
- Heatmap-style grids for attention weights
- Color gradient: white (0) → deep blue/red (1.0)
- Label rows/columns with token names

### Multi-Agent Diagrams
- Each agent as a distinct colored node
- Communication channels as directed edges
- Shared memory/workspace as a central element
- Use swim-lane layout for parallel agent execution

## Recommended Color Scheme
- **Primary**: #3b82f6 (Blue — represents language/text)
- **Secondary**: #8b5cf6 (Purple — represents AI/intelligence)
- **Accent**: #f59e0b (Amber — represents key findings)
- **Success**: #10b981 (Green — represents improvements)
- **Code/Technical**: #64748b (Slate — for technical details)

## Key Metrics to Visualize
- BLEU, ROUGE, METEOR scores → Bar chart or radar chart
- Perplexity → Line chart (lower is better, invert scale)
- Accuracy, F1, Precision, Recall → Grouped bar chart
- Latency/Throughput → Dual-axis chart
- Token cost / API calls → Stacked bar chart for agent systems

## Section Recommendations
1. **Problem Statement**: Clear NLP task definition with input/output examples
2. **Model Architecture**: SVG pipeline diagram with component details
3. **Training Process**: Timeline or flowchart of training stages
4. **Results**: Multi-metric comparison charts
5. **Agent Workflow**: If applicable, agent interaction diagram
6. **Ablation Study**: Table or grouped bar chart
