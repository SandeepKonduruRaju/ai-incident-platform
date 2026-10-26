#!/bin/sh
# Alertmanager for the local "observability" compose profile (milestone 4).
# Alertmanager cannot read environment variables in its config, so this script writes the config at
# container start. Secrets (Slack webhook URL, SMTP password) come ONLY from the environment and end up only
# in /alertmanager/generated inside the container: never in git.
#
# Receivers:
#   webhook-echo   always: every alert is POSTed to the local echo container (docker logs alert-webhook-echo)
#   slack          only if ALERT_SLACK_WEBHOOK_URL is set (channel: ALERT_SLACK_CHANNEL, default #incidents)
#   email          only if ALERT_EMAIL_TO and ALERT_SMTP_SMARTHOST are set
set -eu

out=/alertmanager/generated/alertmanager.yml
mkdir -p /alertmanager/generated

routes=""
receivers=""

if [ -n "${ALERT_SLACK_WEBHOOK_URL:-}" ]; then
  routes="${routes}
    - receiver: slack
      continue: true"
  receivers="${receivers}
  - name: slack
    slack_configs:
      - api_url: '${ALERT_SLACK_WEBHOOK_URL}'
        channel: '${ALERT_SLACK_CHANNEL:-#incidents}'
        send_resolved: true
        title: '{{ .Status | toUpper }}: {{ .CommonLabels.alertname }}'
        text: '{{ range .Alerts }}- {{ .Annotations.summary }} {{ end }}'"
  echo "alertmanager: Slack receiver enabled"
fi

if [ -n "${ALERT_EMAIL_TO:-}" ] && [ -n "${ALERT_SMTP_SMARTHOST:-}" ]; then
  routes="${routes}
    - receiver: email
      continue: true"
  receivers="${receivers}
  - name: email
    email_configs:
      - to: '${ALERT_EMAIL_TO}'
        from: '${ALERT_EMAIL_FROM:-alertmanager@localhost}'
        smarthost: '${ALERT_SMTP_SMARTHOST}'
        auth_username: '${ALERT_SMTP_USERNAME:-}'
        auth_password: '${ALERT_SMTP_PASSWORD:-}'
        send_resolved: true"
  echo "alertmanager: email receiver enabled"
fi

cat > "$out" <<EOF
# GENERATED at container start by entrypoint.sh: do not edit (and never commit a copy: it may hold secrets).
route:
  receiver: webhook-echo
  group_by: [alertname]
  group_wait: 10s
  group_interval: 1m
  repeat_interval: 4h
  routes:
    - receiver: webhook-echo
      continue: true${routes}

receivers:
  - name: webhook-echo
    webhook_configs:
      - url: http://alert-webhook-echo:8080/alerts
        send_resolved: true${receivers}
EOF

exec /bin/alertmanager --config.file="$out" --storage.path=/alertmanager
