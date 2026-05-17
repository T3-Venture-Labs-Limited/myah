# OSS dashboard is bound to 0.0.0.0 (LAN-exposed by default)

**Date discovered:** 2026-05-17
**Affected:** OSS variant (`MYAH_DEPLOYMENT_MODE=oss`); does not affect hosted

## The bug class

Hermes dashboard defaults to `--host 127.0.0.1` (loopback only). On
Linux Docker, the platform container reaches the host via
`host.docker.internal:host-gateway` which resolves to the host bridge
IP (e.g. `172.17.0.1`) — a service bound only to 127.0.0.1 is
unreachable from there. To make the platform container reach the
dashboard, we launch it with `--insecure --host 0.0.0.0`.

This means the dashboard is reachable from EVERY interface — including
the LAN. An attacker on the same network can hit
`http://<your-host-IP>:9119/` and (if the session token leaks via
any other channel) read or modify API keys.

## How to detect

- `ss -tnlp | grep 9119` (or `netstat`/`lsof`) — shows the dashboard
  bound to `0.0.0.0:9119` instead of `127.0.0.1:9119`
- `curl -sI http://<your-LAN-IP>:9119/` from another machine returns
  a response

## How to mitigate

- For production self-host: add a firewall rule (UFW, iptables) that
  blocks 9119 from non-loopback interfaces; only the docker bridge
  needs reach
- For dev/test: accept the exposure; the session token is the only
  defense, and as long as it's a strong random secret, this is
  comparable to any "service-bound-to-LAN" web app
- Future improvement: bind to the docker bridge IP specifically
  rather than 0.0.0.0 (requires detecting the bridge IP at startup
  time — non-trivial across platforms)

## How we prevent regression

- The OSS README explicitly documents this exposure
- The systemd / launchd templates' comments warn about it
- `dev-oss.sh status` could grow a check that warns if 9119 is
  reachable from a non-loopback interface (deferred)
