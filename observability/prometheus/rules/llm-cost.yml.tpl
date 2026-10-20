# Template: compose replaces __LLM_COST_ALERT_USD_PER_HOUR__ with $LLM_COST_ALERT_USD_PER_HOUR (default 1)
# at Prometheus startup and writes the result to /prometheus/generated/llm-cost.yml. Prometheus rule files
# cannot read environment variables themselves.
groups:
  - name: llm-cost
    rules:
      - alert: LLMCostPerHourHigh
        expr: sum(increase(llm_cost_usd_total[1h])) > __LLM_COST_ALERT_USD_PER_HOUR__
        labels:
          severity: warning
        annotations:
          summary: "LLM spend in the last hour is ${{ $value | printf \"%.2f\" }} (threshold $__LLM_COST_ALERT_USD_PER_HOUR__)"
          description: "Check investigation volume, repair attempts and tokens per investigation."
