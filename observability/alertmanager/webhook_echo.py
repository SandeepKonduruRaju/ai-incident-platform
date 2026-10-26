"""Local Alertmanager receiver (milestone 4): prints every webhook notification it gets, one line per alert.

Stands in for Slack/PagerDuty in the local stack, so the alerting path can be tested without any account:
    docker logs -f alert-webhook-echo
Standard library only; listens on :8080 inside the compose network (not published on the host).
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class Echo(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 (http.server naming)
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            payload = json.loads(body)
            for alert in payload.get("alerts", []):
                labels = alert.get("labels", {})
                summary = alert.get("annotations", {}).get("summary", "")
                print(
                    f"[{alert.get('status', '?').upper()}] {labels.get('alertname')} "
                    f"severity={labels.get('severity', '-')}: {summary}",
                    flush=True,
                )
        except ValueError:
            print(f"non-JSON notification: {body[:200]!r}", flush=True)
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_args):  # the alert lines above are the log; skip the access log
        pass


if __name__ == "__main__":
    print("webhook-echo listening on :8080", file=sys.stderr, flush=True)
    HTTPServer(("0.0.0.0", 8080), Echo).serve_forever()  # noqa: S104 (container-internal)
