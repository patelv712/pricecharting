# Paired Validation Comparison

- Cohort size: 100
- Cross-mode cohort identity verified: True
- Disagreements: 61

| Mode | Accuracy | Macro-F1 | Deleted precision | Condition ID accuracy | Human review rate | Cost | p50 latency |
|---|---:|---:|---:|---:|---:|---:|---:|
| rules | 0.400 | 0.292 | 1.000 | 0.167 | 0.840 | $0.0000 | 0 ms |
| text-only | 0.556 | 0.528 | 1.000 | 0.367 | 0.270 | $0.4285 | 11258 ms |
| multimodal | 0.767 | 0.735 | 1.000 | 0.933 | 0.210 | $0.6360 | 11552 ms |

## Paired Image Effect

- Image improved correctness: 20
- Image degraded correctness: 1
- Net improvement: 19

No AI-generated confidence score is used by the active reviewer contract.
