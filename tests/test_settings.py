import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from settings import Settings, read_domains, request_action

CONFIG = Path(__file__).resolve().parents[1] / "config"
if not CONFIG.is_dir():
    CONFIG = Path("/config")


class SettingsTests(unittest.TestCase):
    def load(self, **values):
        return Settings.load({"HOST_IP": "192.168.1.10", **values}, CONFIG)

    def test_no_container_ip_autodetection(self):
        for ip in ("", "127.0.0.1", "0.0.0.0", "224.0.0.1", "255.255.255.255", "::1"):
            with self.subTest(ip=ip), self.assertRaises(ValueError):
                self.load(HOST_IP=ip)

    def test_invalid_env_fails_instead_of_injecting_config(self):
        for values in ({"DNS_MODE": "typo"}, {"UPSTREAM_DNS": "1.1.1.1\nserver=8.8.8.8"},
                       {"UPSTREAM_DNS": "127.0.0.1"}, {"UPSTREAM_DNS": "192.168.1.10"},
                       {"UPSTREAM_DNS": ""}, {"LOG_QUERIES": "yes"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.load(**values)

    def test_selective_has_explicit_upstreams_and_local_zones(self):
        conf = self.load().dnsmasq_config()
        self.assertIn("no-resolv\n", conf)
        self.assertIn("no-hosts\n", conf)
        self.assertIn("server=1.1.1.1\n", conf)
        self.assertIn("local=/playstation.net/\n", conf)
        self.assertIn("local=/manuals.playstation.net/\n", conf)
        self.assertIn("host-record=manuals.playstation.net,192.168.1.10\n", conf)
        self.assertNotIn("log-queries", conf)

    def test_offline_never_forwards(self):
        conf = self.load(DNS_MODE="offline", UPSTREAM_DNS="").dnsmasq_config()
        self.assertIn("address=/#/\n", conf)
        self.assertNotIn("server=", conf)

    def test_domain_list_normalizes_and_rejects_dnsmasq_directives(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "domains"
            path.write_text("# comment\nExample.COM. # comment\nexample.com\n")
            self.assertEqual(read_domains(path), ("example.com",))
            for domain in ("*.example.com", "example.com/server=1.1.1.1", "-bad.com", "a..com"):
                path.write_text(domain)
                with self.subTest(domain=domain), self.assertRaises(ValueError):
                    read_domains(path)

    def test_guide_remains_mandatory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "redirect-domains.txt").write_text("www.playstation.com")
            with self.assertRaisesRegex(ValueError, "manuals"):
                Settings.load({"HOST_IP": "192.168.1.10"}, path)

    def test_only_configured_hosts_are_served(self):
        settings = self.load()
        self.assertEqual(request_action("manuals.playstation.net:443", "/document/en/ps5/index.html", settings), "serve")
        self.assertEqual(request_action("MANUALS.PLAYSTATION.NET", "/app/app.js", settings), "serve")
        self.assertEqual(request_action("192.168.1.10", "/", settings), "serve")
        for host in ("evilmanuals.playstation.net", "manuals.playstation.net.evil.com", "", "evil.com"):
            self.assertEqual(request_action(host, "/", settings), "deny")

    def test_secondary_entry_domains_redirect_to_canonical_origin(self):
        for host in ("www.playstation.com", "get.net.playstation.net", "ps5-autoloader.test"):
            self.assertEqual(request_action(host, "/arbitrary/page", self.load()), "redirect")


if __name__ == "__main__":
    unittest.main()
