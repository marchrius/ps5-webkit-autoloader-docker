# PS5 WebKit Autoloader Docker + DNS

An always-on container providing UDP/TCP DNS, HTTP, and HTTPS. It blocks PSN,
PlayStation updates, and telemetry, and serves the official installer from
[itsPLK/ps5-webkit-autoloader](https://github.com/itsPLK/ps5-webkit-autoloader).
The build downloads release **v0.6.1**, including its embedded frontend and payloads.
Copying the repository's frontend directory alone is insufficient because it
requires generated artifacts. The container does not download updates at startup
and can run without Internet access after the image has been built.

## Getting started

### Devices with port 53 already in use: macvlan

The container receives a dedicated LAN IP without publishing ports on the host,
so the existing DNS service can keep using port 53. This requires a Linux host
or NAS running rootful Docker, Compose v2 with `!reset` support, an Ethernet
interface, and a network that accepts multiple MAC addresses on the same port.

```sh
cp .env.macvlan.example .env
# Set HOST_IP, MACVLAN_PARENT, MACVLAN_SUBNET, and MACVLAN_GATEWAY.
docker compose config
docker compose up -d --build --force-recreate
docker compose logs -f
```

The example uses `HOST_IP=192.168.1.20`, subnet `192.168.1.0/24`, gateway
`192.168.1.1`, and interface `eth0`. Check these values on the target device
using `ip -br addr` and `ip route`. The interface may be named `eno1`, `bond0`,
`ovs_eth0`, or something else. The container IP must be unused, different from
the NAS IP, excluded from the DHCP pool, and within the subnet.
If the NAS uses `192.168.1.10`, assign another unused IP to the container.

`COMPOSE_FILE` in the example automatically loads `compose.yaml` and
`compose.macvlan.yaml`. If your NAS management interface ignores this variable,
configure both files in the project or run the following command explicitly:

```sh
docker compose -f compose.yaml -f compose.macvlan.yaml up -d --build --force-recreate
```

The resulting service configuration must not contain a `ports` section.
Adding a macvlan network to the base file alone is insufficient: the override
also removes the published ports. `BIND_IP` is unused in this mode.
The PS5 must use **the container IP** (`HOST_IP`) for DNS and web access.

By default, a Linux kernel restriction prevents direct communication between
the host and its macvlan containers. Test DNS and web access from the PS5 or
another LAN computer, or run
`docker compose exec dns python /app/healthcheck.py` on the NAS.
To use a DNS service on the same NAS as an upstream resolver, you also need
a macvlan interface on the NAS or an additional network path. The public
resolvers in the example avoid this dependency. The internal healthcheck
continues to work over loopback.
Macvlan is not supported by Docker Desktop for Mac or Windows; run this
configuration on the target Linux device. See the
[Docker macvlan documentation](https://docs.docker.com/engine/network/drivers/macvlan/).

### Reuse an existing macvlan network

If another Docker network already owns the LAN subnet, creating a second one
can fail with `Pool overlaps with other one on this address space`. Reuse the
existing network if it is a macvlan network with the correct LAN parent,
subnet, and gateway. On the target Docker host, inspect it with:

```sh
docker network ls --filter driver=macvlan
docker network inspect YOUR_EXISTING_NETWORK
```

Use the external-network configuration instead of the managed macvlan override:

```sh
cp .env.macvlan-external.example .env
# Set MACVLAN_NETWORK to the exact existing Docker network name.
# Set HOST_IP to an unused address in its subnet, outside the DHCP pool.
docker compose config
docker compose up -d --build --force-recreate
```

In Portainer's Git stack settings, use `compose.yaml` and
`compose.macvlan-external.yaml` as the Compose files. Replace
`compose.macvlan.yaml`; do not include both macvlan variants.
Set `MACVLAN_NETWORK` and `HOST_IP` in the stack environment.
The external definition contains no driver, parent, or IPAM settings: Docker
uses the existing network and Compose does not create or remove it.

If the overlapping network is a bridge network rather than macvlan, it is not
a substitute for direct LAN access. Inspect its subnet and attached containers
before deciding how to resolve the conflict. Avoid deleting active networks
or changing the container to an unrelated subnet: its IP must remain reachable
on the intended LAN.

### Dedicated Docker network on an already-used LAN

If you want a separate Docker network while leaving another service's macvlan
network unchanged, use `compose.macvlan-dedicated.yaml` with a modern Docker
Engine that supports multiple macvlan networks on the same parent interface:

```sh
cp .env.macvlan-dedicated.example .env
# Set HOST_IP, MACVLAN_PARENT, MACVLAN_SUBNET, and an on-link UPSTREAM_DNS.
docker compose config
docker compose up -d --build --force-recreate
```

In Portainer, select `compose.yaml` and `compose.macvlan-dedicated.yaml`, replacing
the other macvlan override. This creates a separate stack-owned network with
the same LAN subnet and a single-address `ip_range` of `HOST_IP/32`. The subnet
mask remains the LAN mask; `/32` restricts Docker's allocation pool only.
Choose an unused address outside the DHCP pool.

This variant deliberately omits `gateway`, since Docker has already allocated
the LAN gateway to the existing network. The container therefore has no default
route. In selective mode, set `UPSTREAM_DNS` to a resolver within the same LAN
subnet, such as the router if it provides DNS. Public resolvers and clients on
other routed subnets are not directly reachable in this mode. `DNS_MODE=offline`
does not need an upstream resolver. The PS5 keeps its normal router gateway.
Downloading the release during image build still uses the builder's network.

The two Docker networks have independent lifecycle management, but remain on
the same physical LAN and are not isolated from each other at layer 2.
For network isolation or a separate routed subnet, use a configured VLAN and
appropriate router/firewall rules instead. Older Engines may reject reuse of
the parent interface; use the external-network variant in that case.

### Alternative: published ports

This configuration requires Docker with Compose v2 and a stable LAN IPv4
address for the server. Use it when the host ports are available.

```sh
cp .env.example .env
# Set HOST_IP in .env to the computer/NAS LAN IPv4 address, e.g. 192.168.1.10.
docker compose up -d --build
docker compose logs -f
```

### Local macOS testing when standard ports are in use

Use high ports to avoid conflicts with services on the Mac or the Colima VM.
The macvlan configuration in `.env` remains separate:

```sh
cp .env.macos.example .env.macos
# Set HOST_IP to the Mac's LAN IPv4 address.
docker compose --env-file .env.macos -f compose.yaml up -d --build --force-recreate
dig @127.0.0.1 -p 1053 manuals.playstation.net A +short +time=2 +tries=1
dig +tcp @127.0.0.1 -p 1053 manuals.playstation.net A +short +time=2 +tries=1
curl --fail http://127.0.0.1:8080/document/en/ps5/index.html -o /dev/null
curl --fail -k --resolve manuals.playstation.net:8443:127.0.0.1 \
  https://manuals.playstation.net:8443/document/en/ps5/index.html -o /dev/null
```

DNS queries should return `HOST_IP`, and web requests should succeed.
Open `http://127.0.0.1:8080/` in your browser. For HTTPS testing, use the User's
Guide path above: secondary entry domains redirect to standard port 443 and
are unsuitable for testing with high ports. If loopback works but the Mac's
LAN IP does not, check the firewall and Colima port forwarding.
With Colima, `portForwarder: ssh` forwards TCP only: `dig +tcp` works while
UDP queries time out. To test UDP as well, use the `grpc` forwarder, which
Colima marks as experimental:

```sh
# Restarting Colima temporarily interrupts its other containers as well.
colima stop
colima start --port-forwarder grpc
```

Then start the project again with the same Compose command and repeat the queries.
See the [official Colima configuration](https://github.com/abiosoft/colima/blob/main/embedded/defaults/colima.yaml).
The PS5 requires DNS on port 53. Alternative ports are for computer-based tests;
the macvlan container on the NAS continues to use ports 53, 80, and 443.

### Updating a deployment after service or network renames

Service and stack-owned network names are resource identities in Compose.
Before deploying renamed resources with the same static IP or single-address
pool, remove the previous PS5 stack using its saved original configuration.
Ensure its previous container and stack-owned macvlan network are removed
before deploying the updated stack. In Portainer, remove the previous PS5 stack
and redeploy it with the updated files. Keep unrelated service networks intact;
external networks are not removed by Compose.

### Console setup

Set the PS5's primary DNS server to `HOST_IP`. For secondary DNS, use the same
IP if allowed, or a second server with the same rules. Do not use a public DNS
server as the secondary: it could bypass the block. Keep the router as the gateway.
Disable automatic updates in the console settings.

Open **Settings → User's Guide**; the exact menu path depends on the firmware.
The container serves `https://manuals.playstation.net/document/en/ps5/index.html`.
Follow the upstream installer, then use the WebKit Autoloader shortcut created
on the console. The container can remain running as a DNS filter.
Firmware support and installation results depend on the upstream release.

With published ports, **53 UDP/TCP, 80 TCP, and 443 TCP** must be available and
reachable from the console. Compose publishes them on `BIND_IP`, which defaults
to `0.0.0.0` (all IPv4 interfaces). `HOST_IP` is the address returned to the PS5
by DNS. On native Linux, set `BIND_IP` to the server's LAN IP to restrict binding.
A DNS service listening on all interfaces can already occupy port 53.
The PS5 does not support alternative DNS ports.
On macOS or Windows, use the computer's IP rather than the Docker VM's IP;
also check the firewall and Docker Desktop/Colima UDP forwarding.
On Linux, bridge networking with published ports is sufficient;
`network_mode: host` is unnecessary.

If Docker reports `cannot assign requested address`, the bind address is not
available on the system running the daemon, such as the Colima VM.
Set `BIND_IP=0.0.0.0` and recreate the container with
`docker compose up -d --force-recreate`. Keep `HOST_IP` set to the IPv4 address
the PS5 can actually reach, rather than the container's internal bridge IP.

`restart: unless-stopped` restarts the container after a crash or daemon restart.
Docker must start automatically with the server. The supervisor exits if DNS
or web services stop or fail three consecutive healthchecks, allowing Docker
to restart the container. Docker's `unhealthy` status alone would not normally
trigger a restart.

## Managed domains and pages

The active policy is defined by three editable files mounted read-only from
`config/`. The inventory below matches the configuration validated on a PS5 on
**October 26, 2026**: **5 whitelist entries, 49 blacklist suffixes, and 4 local
redirect domains**.

| File | Purpose |
| --- | --- |
| [whitelist-domains.txt](config/whitelist-domains.txt) | Forward selected domains through blocked parent suffixes in `selective` mode |
| [blocked-domains.txt](config/blocked-domains.txt) | Return NXDOMAIN for configured suffixes, except more specific allowed or local entries |
| [redirect-domains.txt](config/redirect-domains.txt) | Resolve exact entry domains to `HOST_IP` and serve or redirect their web requests locally |

All files accept one domain per line, blank lines, and `#` comments. Do not use
wildcards. Blacklist and whitelist entries cover the domain and its subdomains.
The most specific DNS suffix wins: a whitelist entry overrides a blocked parent,
while a more specific blacklist entry remains blocked. Avoid putting the same
suffix in both lists: a local blocking rule prevents forwarding at that suffix.

`DNS_MODE=selective` forwards other queries to `UPSTREAM_DNS`.
`DNS_MODE=offline` ignores whitelist forwarding and blocks other names while
preserving local entry domains. Neither mode is a firewall.

### Whitelist: allowed domains

| Domain | Documented role and current reason for allowing it |
| --- | --- |
| `ena.net.playstation.net` | Internet connection status check, inferred by the domain study from the `SceIcst` User-Agent. Successfully resolved during the PS5 connection test. |
| `post.net.playstation.net` | Historical PlayStation upload-test endpoint. Successfully resolved during this PS5's test, which completed upload measurement. It is absent from the domain study's README. |
| `gst.prod.dl.playstation.net` | PS5 game patch PKG downloads according to the study. Successfully resolved during this PS5's test, which completed download measurement. Its speed-test role is an observation to investigate, not a classification supplied by the study. Allowing it also permits game patch content; it is separate from console firmware. |
| `smetrics.aem.playstation.com` | Telemetry/analytics endpoint; the study mentions a possible trophy-system relationship. Explicitly allowed at the user's request and resolved during the successful test. Its necessity for speed measurement has not been established. |
| `us.np.stun.playstation.net` | Listed under NP domains without a function description in the study. STUN/NAT discovery is inferred from its name; DNS resolution succeeded during this PS5's test. The supplied result does not establish the NAT-test outcome. |

The whitelist uses the configured upstream resolver, not the local web host.
Comment out an entry to restore its parent block. An empty or missing whitelist
keeps configured blocks in effect. A whitelist entry equal to or below a local
redirect zone is rejected at startup; remove an optional redirect first if you
want to forward that domain. Keep `manuals.playstation.net` in the redirect list.

**Telemetry exception:** the current policy allows `smetrics.aem.playstation.com`.
It therefore blocks the telemetry endpoints listed below, but does not block all
telemetry. The successful batch test does not prove that every whitelist entry
is required; testing one removed exception at a time would establish that.

### Blacklist: blocked domains

The blacklist contains 6 broad suffixes, 1 firmware parent suffix, 39 explicit
regional firmware hosts, and 3 telemetry suffixes (49 entries total).

| Broad suffix | Coverage |
| --- | --- |
| `playstation.net` | PlayStation services, including PSN, update/CDN and RNPS hosts, subject to the explicit exceptions |
| `playstation.com` | PlayStation website/API and telemetry hosts, subject to the explicit exceptions |
| `playstation.org` | Domain and all subdomains |
| `scea.com` | Domain and all subdomains |
| `sonyentertainmentnetwork.com` | Domain and all subdomains |
| `sie-rd.com` | Domain and all subdomains |

**Console firmware:** `ps5.update.playstation.net` blocks the whole firmware
namespace, including regional hosts beyond the explicit list. The explicit
regional entries preserve their blocks if a broader parent is later allowed.
The domain study identifies three host families:

| Host family | Purpose |
| --- | --- |
| `fXX01.ps5.update.playstation.net` | Firmware version checks: XML manifests, PUP URLs, and minimum firmware required per game |
| `dXX01.ps5.update.playstation.net` | Firmware PUP downloads |
| `hXX01.ps5.update.playstation.net` | Update information / “About this update” pages |

All 39 explicit hosts are listed below. Append `.ps5.update.playstation.net`
to each host label; `XX` above is explanatory notation, not configuration syntax.

| Region code | Version check | Firmware download | Update information |
| --- | --- | --- | --- |
| `au` | `fau01` | `dau01` | `hau01` |
| `br` | `fbr01` | `dbr01` | `hbr01` |
| `cn` | `fcn01` | `dcn01` | `hcn01` |
| `eu` | `feu01` | `deu01` | `heu01` |
| `hk` | `fhk01` | `dhk01` | `hhk01` |
| `jp` | `fjp01` | `djp01` | `hjp01` |
| `kr` | `fkr01` | `dkr01` | `hkr01` |
| `mx` | `fmx01` | `dmx01` | `hmx01` |
| `ru` | `fru01` | `dru01` | `hru01` |
| `sa` | `fsa01` | `dsa01` | `hsa01` |
| `tw` | `ftw01` | `dtw01` | `htw01` |
| `uk` | `fuk01` | `duk01` | `huk01` |
| `us` | `fus01` | `dus01` | `hus01` |

**Explicit telemetry blocks:**

| Domain | Role described by the study |
| --- | --- |
| `telemetry-console.api.playstation.com` | Probably synchronizes playtime and games played; detailed purpose inferred |
| `telemetry-web.api.playstation.com` | Possibly tracks browser usage; detailed purpose inferred |
| `telemetry-schema-app.rnps.dl.playstation.net` | Likely downloads the telemetry schema at boot; role inferred |

Other hosts observed returning NXDOMAIN through the broad parent blocks include
`ps5.np.playstation.net`, `envelope2.np.dl.playstation.net`,
`ppr-crl.rnps.dl.playstation.net`, `qgve.dl.playstation.net`,
`feature.api.playstation.com`, and
`feature-discovery-assets-amd.dl.playstation.net`. They are not extra explicit
blacklist entries. The study does not assign a verified role to all of them;
RNPS feature updates are distinct from console firmware updates.

### Redirects: local entry domains

Each configured domain gets an exact local A record pointing to `HOST_IP`.
Its DNS zone stays local: AAAA, HTTPS/SVCB, and queries below that zone are not
forwarded upstream. Subdomains do not automatically receive the exact host's
A record. Web behavior is separate from DNS resolution:

| Domain | Local web behavior |
| --- | --- |
| `manuals.playstation.net` | Serves the official upstream frontend at `/document/<language>/ps5/index.html`; other assets depend on the upstream release |
| `www.playstation.com` | Redirects to the local User's Guide origin |
| `get.net.playstation.net` | Redirects to the local User's Guide origin; a historical connection-test endpoint, currently kept local |
| `ps5-autoloader.test` | Local browser-testing alias that redirects to the User's Guide origin |

Direct HTTP access through `HOST_IP` also serves the frontend. Extra entry
domains do not guarantee that the PS5 connection test opens a browser. Use
**Settings → User's Guide** for the documented installation flow.

### PS5 validation: October 26, 2026

The user confirmed successful **download and upload speed measurements** with
all five whitelist exceptions active. The tested setup used:

| Setting | Tested value |
| --- | --- |
| PS5 | `192.168.3.64`, automatic IP configuration, manual DNS pointing to the container |
| DNS / web container (`HOST_IP`) | `192.168.3.201` |
| Mode | `selective` |
| Upstream LAN DNS | `192.168.3.254` |

The logs show successful public DNS responses for `ena`, `post`, `gst`,
`smetrics`, and `us.np.stun`; `fuk01.ps5.update.playstation.net`,
`ps5.np.playstation.net`, and `telemetry-console.api.playstation.com` still
returned NXDOMAIN. `manuals.playstation.net` resolved to `192.168.3.201`, and
local HTTP healthcheck requests returned 200.

`get.net.playstation.net` remained redirected and was not queried in the supplied
successful test. The logs show DNS resolution, not HTTP transfers or their
contents; the speed-test success comes from the user's console result. These
results do not establish successful PSN access, a NAT type, the necessity of
each exception, or the behavior of other firmware/network configurations.
Repeated queries for blocked hosts show repeated console requests; the
`config ... is NXDOMAIN` replies confirm the block remains active.

In this dedicated macvlan setup the container has no default route, so its
upstream DNS must be reachable within the LAN subnet. `192.168.3.254` answered
the supplied DNS probes; `192.168.3.1` timed out. Keep the PS5's normal router
gateway and point its DNS to the container, rather than to the upstream resolver.

Domain classifications come from the supplied
[Yelodress domain study](https://github.com/Yelodress/understanding-ps5-domains),
which studied firmware 14.00 without PSN access and marks several roles as
inferred. The study does not list `get` or `post`, or identify a dedicated
speed-test host. Historical network-test grouping is also documented in
[Al-Azif's configuration notes](https://gist.github.com/Al-Azif/296c7a4319c2fe3b597d96206213cdb6).
The observations above describe this deployment and do not change those source
classifications.

### Apply changes and inspect the policy

After editing any of the three domain files:

```sh
docker compose restart
```

Reconnect the PS5 network before repeating its test. Code/image changes require
`docker compose up -d --build --force-recreate`; environment changes require
container recreation. Use the same Compose files and environment as the existing
deployment.

With `LOG_QUERIES=true`, inspect the generated policy and live replies:

```sh
docker compose exec dns cat /run/dnsmasq.conf
docker compose logs --follow --tail 0 --timestamps dns
```

For the tested deployment, run these probes from another LAN device:

```sh
# Expected: upstream DNS answers (CNAME chains and public addresses may change).
for domain in ena.net.playstation.net post.net.playstation.net \
  gst.prod.dl.playstation.net smetrics.aem.playstation.com \
  us.np.stun.playstation.net; do
  dig @192.168.3.201 "$domain" A +time=2 +tries=1
done
# Expected: NXDOMAIN.
dig @192.168.3.201 fuk01.ps5.update.playstation.net A
dig @192.168.3.201 telemetry-console.api.playstation.com A
# Expected: 192.168.3.201 for A; no upstream forwarding for AAAA.
dig @192.168.3.201 manuals.playstation.net A
dig @192.168.3.201 manuals.playstation.net AAAA
```

Settings in `.env`:

| Variable | Meaning |
| --- | --- |
| `HOST_IP` | Required: dedicated container IP with macvlan, or server IP with published ports |
| `COMPOSE_FILE` | On Linux: `compose.yaml` plus the selected macvlan override, separated by `:`; see the three variants above |
| `MACVLAN_NETWORK` | External macvlan only: exact name of the existing Docker network |
| `MACVLAN_PARENT` | LAN interface on the Docker host, e.g. `eth0` or `bond0` |
| `MACVLAN_SUBNET` | LAN subnet in CIDR notation, e.g. `192.168.1.0/24` |
| `MACVLAN_GATEWAY` | LAN router IPv4 address; used only by the standard managed macvlan variant |
| `BIND_IP` | Published ports only: bind address, default `0.0.0.0` |
| `DNS_PORT`, `HTTP_PORT`, `HTTPS_PORT` | Published ports only: defaults 53, 80, and 443; use 1053, 8080, and 8443 for Mac tests |
| `DNS_MODE=selective` | Blocks configured suffixes and forwards other names upstream |
| `DNS_MODE=offline` | Blocks all names except local exceptions; no DNS forwarding |
| `UPSTREAM_DNS` | Comma-separated resolver IPs, default `1.1.1.1,9.9.9.9`; the dedicated `/32` pool variant requires a resolver on its LAN in selective mode |
| `LOG_QUERIES=true` | Records DNS queries in Docker logs |
| `AUTOLOADER_VERSION` | Stable release downloaded during the build |
| `AUTOLOADER_SHA256` | Optional: expected digest of the release's host `.py` file |

To apply `.env` changes, run `docker compose up -d --build`.
To add a browser entry domain, add its exact name to `redirect-domains.txt`.
It will resolve locally and redirect to the canonical User's Guide origin.

## HTTPS and blocking limitations

The container generates a self-signed certificate for the configured domains
at each startup, avoiding reuse of the public private key embedded in the release.
A computer browser will display a warning. Console acceptance depends on the
firmware and browser context, as with the upstream host. DNS alone does not
make a certificate trusted or bypass HSTS/certificate pinning. Prefer the User's
Guide; transparent interception of every HTTPS page is not guaranteed.

PSN, Store, and related services will stop working. The filter applies to
queries sent through this DNS server. It is not a firewall and does not block
direct IP access, encrypted DNS, alternative resolvers, or updates already
downloaded. For complete isolation, also apply router rules and account for
IPv6/DNS advertised through RA/DHCPv6. The `offline` mode also concerns DNS
resolution, rather than all console IP traffic.
Do not expose the service through Internet port forwarding; it is intended for LAN use.

## Verification

Replace `192.168.1.10` with `HOST_IP`:

```sh
docker compose ps
dig @192.168.1.10 manuals.playstation.net A +short
# Expected: 192.168.1.10
dig +tcp @192.168.1.10 manuals.playstation.net A +short
dig @192.168.1.10 manuals.playstation.net AAAA
# Expected: no AAAA record
dig @192.168.1.10 feu01.ps5.update.playstation.net A
# Expected: NXDOMAIN
dig @192.168.1.10 telemetry-console.api.playstation.com AAAA
# Expected: NXDOMAIN
dig @192.168.1.10 example.org A
# selective: upstream response; offline: NXDOMAIN
curl -k --resolve manuals.playstation.net:443:192.168.1.10 \
  https://manuals.playstation.net/document/en/ps5/index.html
curl -I --resolve www.playstation.com:80:192.168.1.10 http://www.playstation.com/
# Expected: 302 redirect to https://manuals.playstation.net/
docker compose exec dns python /app/healthcheck.py
```

Run local tests without external Python dependencies:

```sh
python3 -m unittest discover -s tests -v
```

Real DNS tests are skipped if `dnsmasq` is not installed. To run them using
the image's binary after building, without publishing ports:

```sh
docker run --rm --entrypoint python \
  -v "$PWD/tests:/app/tests:ro" ps5-webkit-autoloader-dns:local \
  -m unittest discover -s /app/tests -v
```

## Updates and provenance

### Image size

The image uses a multi-stage build. Python 3.13 comes from the official
`python:3.13-alpine3.24` image; the final base is `alpine:3.24` with the same ABI.
Only the trimmed Python installation, its native runtime dependencies, the
service packages, application files, and upstream release artifacts are copied
into the final image. `pip`, `ensurepip`, Python development headers, and build
configuration files are removed before that copy, so they do not remain in
lower image layers. The Python standard library and HTTPS support are retained.

### Release updates

To update, select a published stable release in `.env` and rebuild.
Releases 0.5.2 and 0.6.1 use direct official download URLs and checked-in,
verified SHA-256 digests, without calling the GitHub API. Other versions use
the API to discover the published Python asset and its digest when available. A nonexistent
version produces an explicit error and is not replaced automatically.
The integration handles the HTTP APIs of releases 0.5.2 and 0.6.1.
It does not use a moving `latest` reference. The actual digest and download URL
are recorded in `/app/UPSTREAM.txt`; the upstream license is in `/app/LICENSE.upstream`.
You can set a digest from a verified source in `AUTOLOADER_SHA256`.
The integration does not modify the release's frontend or payload files.
Distributing images containing the GPL-3.0 upstream software requires compliance
with its license and corresponding source-code obligations.

### Portainer build failures

The default `image: ps5-webkit-autoloader-dns:local` is a local build tag, not
a published Docker Hub image. The service uses `pull_policy: build` so Compose
builds it from the repository and skips it during `compose pull`. Deploy this
configuration from the Git repository, including the build context and Dockerfile.
Disable any Portainer option that explicitly forces an image re-pull for this
stack. Running `docker login` will not make this local tag available in a registry.
For Docker Swarm deployments, build and publish an image separately before
deploying; Swarm does not build the image from this Compose definition.

If Portainer reports only `fetch_release.py ... exit code: 1`, check the build
log immediately before it for `Autoloader download failed`. That line identifies
the failing step and HTTP status. API HTTP 403 can indicate GitHub's anonymous
rate limit; the pinned default release avoids that API call entirely.
An asset HTTP 404 can indicate a missing release or file, while DNS, connection,
or certificate errors require checking outbound HTTPS access from the Docker host.
The build needs access to `github.com`, its release-asset redirect hosts, and
`raw.githubusercontent.com` for the upstream license. Runtime does not need
these download endpoints.

For a Portainer stack built from this repository, select the updated commit,
keep `AUTOLOADER_VERSION=0.6.1`, and rebuild/redeploy. No GitHub token is needed
for the pinned release.

## License

The integration code in this repository is distributed under the
**GNU General Public License v3.0** (`GPL-3.0-only`). The complete text is in
[LICENSE](LICENSE), also included in the image at `/app/LICENSE`.
The upstream project and third-party components retain their respective
licenses and attribution notices. The downloaded upstream license is at
`/app/LICENSE.upstream`.

Sources consulted on October 23, 2026:

- [Official v0.6.1 release and assets](https://github.com/itsPLK/ps5-webkit-autoloader/releases/tag/v0.6.1).
- [Official host for the same version](https://github.com/itsPLK/ps5-webkit-autoloader/blob/v0.6.1/pc-host/host.py): User's Guide handling and embedded content.
- [Al-Azif configuration](https://github.com/Al-Azif/ps4-exploit-host/blob/master/settings.json): PlayStation blocking suffixes and web entry domains.
- [PS5 domain research](https://github.com/Yelodress/understanding-ps5-domains): regional servers and telemetry; the author marks some descriptions as unverified.
- [dnsmasq manual](https://thekelleys.org.uk/dnsmasq/docs/dnsmasq-man.html): local zones and static records.
