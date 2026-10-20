# Gateway operations

The gateway routes user traffic between the radio network and the packet core.

## Upgrade the gateway

Upgrade one gateway pod at a time, so the other pods keep routing traffic.

Before you start, check these prerequisites:

- A Kubernetes cluster in version 1.29 or later.
- Helm in version 3.14 or later.

To upgrade the gateway, follow these steps:

1. Back up the gateway configuration with `kubectl get configmap gateway-config -o yaml > backup.yaml`.
2. Install the gateway Helm chart in version 1.7.0.
3. Check that every gateway pod reports `Ready` with `kubectl get pods -l app=gateway`.

If a pod stays in `CrashLoopBackOff` for more than five minutes, roll back with `helm rollback gateway`.

### Log settings

The gateway reads these environment variables at startup:

| Variable | Default | Description |
| --- | --- | --- |
| GATEWAY_LOG_LEVEL | info | Sets the log level. Use debug to log every request. |
| GATEWAY_LOG_FORMAT | text | Sets the log format. Use json for log collectors. |

Restart the gateway pod after you change a variable, because the gateway reads them only at startup.

### Rollback checks

- Confirm the previous chart version with `helm history gateway`.
- Check that the user sessions recover within two minutes.

## Monitor the gateway

The gateway exports Prometheus metrics on port 9090. Scrape them every 30 seconds.
