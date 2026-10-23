"""Validated inputs shared by DNS and HTTP; configuration never becomes shell code."""
import ipaddress
import os
import re
from dataclasses import dataclass
from pathlib import Path


def read_domains(path):
    domains = []
    for line in path.read_text().splitlines():
        name = line.split("#", 1)[0].strip().lower().rstrip(".")
        if not name:
            continue
        if len(name) > 253 or not all(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part)
            for part in name.split(".")
        ):
            raise ValueError(f"Invalid domain in {path}: {name!r}")
        if name not in domains:
            domains.append(name)
    return tuple(domains)


@dataclass(frozen=True)
class Settings:
    host_ip: str
    mode: str
    upstream: tuple
    blocked: tuple
    redirects: tuple
    log_queries: bool = False

    @classmethod
    def load(cls, env=None, directory=Path("/config")):
        env = os.environ if env is None else env
        ip = ipaddress.IPv4Address(env.get("HOST_IP", ""))
        if ip.is_loopback or ip.is_unspecified or ip.is_multicast or str(ip) == "255.255.255.255":
            raise ValueError("HOST_IP must be a LAN IPv4 address reachable from the PS5")
        mode = env.get("DNS_MODE", "selective")
        if mode not in ("selective", "offline"):
            raise ValueError("DNS_MODE must be selective or offline")
        upstream = tuple(str(ipaddress.ip_address(x.strip())) for x in
                         env.get("UPSTREAM_DNS", "1.1.1.1,9.9.9.9").split(",") if x.strip())
        if mode == "selective" and not upstream:
            raise ValueError("UPSTREAM_DNS cannot be empty in selective mode")
        if any(ipaddress.ip_address(x).is_loopback or x == str(ip)
               or ipaddress.ip_address(x).is_unspecified for x in upstream):
            raise ValueError("UPSTREAM_DNS must not point to this server or loopback")
        redirects = read_domains(directory / "redirect-domains.txt")
        if "manuals.playstation.net" not in redirects:
            raise ValueError("Keep manuals.playstation.net in the redirect list")
        logging = env.get("LOG_QUERIES", "false").lower()
        if logging not in ("true", "false"):
            raise ValueError("LOG_QUERIES must be true or false")
        return cls(str(ip), mode, upstream, read_domains(directory / "blocked-domains.txt"),
                   redirects, logging == "true")

    def dnsmasq_config(self):
        lines = ["port=53", "no-resolv", "no-hosts", "domain-needed", "bogus-priv",
                 "cache-size=1000", "local-ttl=60", "log-facility=-", "user=root", "group=root",
                 "pid-file=/run/dnsmasq.pid"]
        if self.log_queries:
            lines.append("log-queries=extra")
        if self.mode == "offline":
            lines.append("address=/#/")
        else:
            lines.extend(f"server={ip}" for ip in self.upstream)
        lines.extend(f"local=/{domain}/" for domain in self.blocked)
        for domain in self.redirects:
            # Local-only zone prevents AAAA/HTTPS/SVCB requests escaping to upstream.
            lines.extend((f"local=/{domain}/", f"host-record={domain},{self.host_ip}"))
        return "\n".join(lines) + "\n"


def request_action(host, path, settings):
    """Decide entry-page redirects without turning asset 404s into HTML."""
    host = host.split(":", 1)[0].lower().rstrip(".")
    if host not in (*settings.redirects, settings.host_ip, "127.0.0.1", "localhost"):
        return "deny"
    if host in settings.redirects and host != "manuals.playstation.net":
        return "redirect"
    return "serve"
