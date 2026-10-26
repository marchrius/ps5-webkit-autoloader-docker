"""Real dnsmasq probes. Skipped when dnsmasq is not installed on the host."""
import shutil
import select
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from settings import Settings
from healthcheck import receive_exact

CONFIG = Path(__file__).resolve().parents[1] / "config"
if not CONFIG.is_dir():
    CONFIG = Path("/config")


@unittest.skipUnless(shutil.which("dnsmasq"), "dnsmasq is not installed; run inside the container")
class DNSIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        # This test must never send traffic to public resolvers.
        settings = self.make_settings()
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
                self.fail("dnsmasq failed to start with the generated configuration")
            try:
                self.query("manuals.playstation.net")
                break
            except OSError:
                time.sleep(0.05)
        else:
            self.fail("dnsmasq is not responding")

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
        self.process.wait(timeout=5)

    def make_settings(self):
        return Settings.load({"HOST_IP": "192.168.1.10", "DNS_MODE": "offline"}, CONFIG)

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


class WhitelistDNSIntegrationTests(DNSIntegrationTests):
    def setUp(self):
        # A local fake upstream proves forwarding without Internet access.
        self.upstream_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.upstream_socket.bind(("127.0.0.1", 0))
        self.upstream_tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.upstream_tcp.bind(self.upstream_socket.getsockname())
        self.upstream_tcp.listen()
        self.upstream_stop = threading.Event()
        self.forwarded = []
        self.upstream_thread = threading.Thread(target=self.serve_upstream, daemon=True)
        self.upstream_thread.start()
        self.addCleanup(self.stop_upstream)
        super().setUp()

    def make_settings(self):
        settings = Settings.load({"HOST_IP": "192.168.1.10"}, CONFIG)
        port = self.upstream_socket.getsockname()[1]
        return replace(settings, upstream=(f"127.0.0.1#{port}",),
                       whitelist=("ena.net.playstation.net",))

    def serve_upstream(self):
        while not self.upstream_stop.is_set():
            readable, _, _ = select.select([self.upstream_socket, self.upstream_tcp], [], [], 0.1)
            for sock in readable:
                if sock is self.upstream_tcp:
                    with sock.accept()[0] as connection:
                        connection.settimeout(1)
                        length = struct.unpack("!H", receive_exact(connection, 2))[0]
                        response = self.upstream_response(receive_exact(connection, length))
                        connection.sendall(struct.pack("!H", len(response)) + response)
                else:
                    query, peer = sock.recvfrom(4096)
                    sock.sendto(self.upstream_response(query), peer)

    def upstream_response(self, query):
        self.forwarded.append(query)
        # Parse the question separately from dnsmasq's optional EDNS record.
        offset = 12
        while query[offset]:
            offset += query[offset] + 1
        offset += 1
        qtype = struct.unpack("!H", query[offset:offset + 2])[0]
        answer = (b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 60, 4)
                  + socket.inet_aton("203.0.113.7")) if qtype == 1 else b""
        return (query[:2] + struct.pack("!5H", 0x8180, 1, int(bool(answer)), 0, 0)
                + query[12:offset + 4] + answer)

    def stop_upstream(self):
        self.upstream_stop.set()
        self.upstream_thread.join(timeout=2)
        self.upstream_socket.close()
        self.upstream_tcp.close()

    def test_whitelist_overrides_parent_block_for_both_transports(self):
        for domain in ("ena.net.playstation.net", "child.ena.net.playstation.net"):
            for tcp in (False, True):
                with self.subTest(domain=domain, tcp=tcp):
                    code, count, data = self.query(domain, tcp=tcp)
                    self.assertEqual((code, count), (0, 1))
                    self.assertTrue(data.endswith(socket.inet_aton("203.0.113.7")))
        self.assertTrue(self.forwarded)

    def test_sibling_blocks_and_redirects_never_reach_upstream(self):
        for domain in ("post.net.playstation.net", "fuk01.ps5.update.playstation.net",
                       "notena.net.playstation.net", "telemetry-console.api.playstation.com"):
            for qtype in (1, 28, 65):
                self.assertEqual(self.query(domain, qtype)[:2], (3, 0))
        self.test_guide_exception_and_both_transports()
        self.test_ipv6_and_https_records_cannot_bypass_redirect()
        self.assertEqual(self.forwarded, [])

    def test_blocked_suffixes_and_unknown_domains(self):
        # Unknown names are forwarded in selective mode; parent zones stay local.
        self.assertEqual(self.query("playstation.net")[:2], (0, 0))


if __name__ == "__main__":
    unittest.main()
