"""Real dnsmasq probes. Skipped when dnsmasq is not installed on the host."""
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from settings import Settings
from healthcheck import receive_exact

CONFIG = Path(__file__).resolve().parents[1] / "config"
if not CONFIG.is_dir():
    CONFIG = Path("/config")


@unittest.skipUnless(shutil.which("dnsmasq"), "dnsmasq non installato; eseguire nel container")
class DNSIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        # This test must never send traffic to public resolvers.
        settings = Settings.load({"HOST_IP": "192.168.1.10", "DNS_MODE": "offline"}, CONFIG)
        conf = settings.dnsmasq_config().replace("port=53\n", f"port={self.port}\n")
        conf = conf.replace("user=root\n", "")
        conf = conf.replace("group=root\n", "")
        conf = conf.replace("pid-file=/run/dnsmasq.pid", "pid-file=")
        path = Path(self.directory.name) / "dnsmasq.conf"
        path.write_text(conf)
        self.process = subprocess.Popen(["dnsmasq", "--keep-in-foreground", f"--conf-file={path}"],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.stop)
        for _ in range(40):
            if self.process.poll() is not None:
                self.fail("dnsmasq non parte con la configurazione generata")
            try:
                self.query("manuals.playstation.net")
                break
            except OSError:
                time.sleep(0.05)
        else:
            self.fail("dnsmasq non risponde")

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
        self.process.wait(timeout=5)

    def query(self, domain, qtype=1, tcp=False):
        name = b"".join(bytes([len(part)]) + part.encode() for part in domain.split(".")) + b"\0"
        query = struct.pack("!6H", 123, 0x100, 1, 0, 0, 0) + name + struct.pack("!2H", qtype, 1)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM) as sock:
            sock.settimeout(0.2)
            sock.connect(("127.0.0.1", self.port))
            if tcp:
                sock.sendall(struct.pack("!H", len(query)) + query)
                length = struct.unpack("!H", receive_exact(sock, 2))[0]
                data = receive_exact(sock, length)
            else:
                sock.send(query)
                data = sock.recv(4096)
        header = struct.unpack("!6H", data[:12])
        return header[1] & 15, header[3], data

    def test_guide_exception_and_both_transports(self):
        for tcp in (False, True):
            code, count, data = self.query("manuals.playstation.net", tcp=tcp)
            self.assertEqual((code, count), (0, 1))
            self.assertTrue(data.endswith(socket.inet_aton("192.168.1.10")))

    def test_blocked_suffixes_and_unknown_domains(self):
        for domain in ("playstation.net", "feu01.ps5.update.playstation.net",
                       "telemetry-console.api.playstation.com", "example.org"):
            for qtype in (1, 28, 65):
                with self.subTest(domain=domain, qtype=qtype):
                    code, answers, _ = self.query(domain, qtype)
                    self.assertEqual(answers, 0)
                    # A parent of configured local host records can exist as an
                    # empty nonterminal (NOERROR/NODATA), still with no address.
                    self.assertIn(code, (0, 3) if domain == "playstation.net" else (3,))

    def test_ipv6_and_https_records_cannot_bypass_redirect(self):
        for qtype in (28, 65):
            self.assertEqual(self.query("manuals.playstation.net", qtype)[:2], (0, 0))


if __name__ == "__main__":
    unittest.main()
