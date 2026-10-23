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
`docker compose exec ps5-host python /app/healthcheck.py` on the NAS.
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

The lists in `config/` are editable and mounted read-only inside the container.
Run `docker compose restart` after changing them.

| Domain | Behavior |
| --- | --- |
| `manuals.playstation.net` | Serves the upstream frontend through `/document/<language>/ps5/`; other file paths depend on the release |
| `www.playstation.com` | Redirects web requests to the local User's Guide root |
| `get.net.playstation.net` | Redirects web requests to the local User's Guide; a historical connection-test endpoint |
| `ps5-autoloader.test` | Local alias that redirects to the User's Guide |
| `HOST_IP` (the container IP with macvlan) | Direct frontend access, useful for HTTP tests |

Entry domains other than the User's Guide are additional options: the connection
test may simply fail without opening a browser on the PS5. The installation
method documented upstream remains the User's Guide. This service does not
simulate successful PSN access or a successful speed test.
Update endpoints, `post`, and `ena` remain blocked.

`blocked-domains.txt` contains the suffixes `playstation.net`, `playstation.com`,
`playstation.org`, `scea.com`, `sonyentertainmentnetwork.com`, and `sie-rd.com`.
Blocking covers each domain and its subdomains, including all regional
`fXX01`, `dXX01`, and `hXX01.ps5.update.playstation.net` servers, CDN, Store,
and authentication services. Entries in `redirect-domains.txt` create exact
local A records. AAAA and other DNS query types for those domains are not
forwarded upstream. This is not a list of individual CDN IP addresses.

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
docker compose exec ps5-host python /app/healthcheck.py
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
