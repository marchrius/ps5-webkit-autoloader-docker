"""Probe both DNS transports and the real HTTP/HTTPS guide page."""
import http.client
import os
import socket
import ssl
import struct


def receive_exact(sock, size):
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise RuntimeError("Risposta DNS TCP incompleta")
        data += chunk
    return data


def check():
    name = b"\x07manuals\x0bplaystation\x03net\0"
    query = struct.pack("!6H", 0x5053, 0x100, 1, 0, 0, 0) + name + struct.pack("!2H", 1, 1)
    for tcp in (False, True):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM) as sock:
            sock.settimeout(2)
            sock.connect(("127.0.0.1", 53))
            if tcp:
                sock.sendall(struct.pack("!H", len(query)) + query)
                length = struct.unpack("!H", receive_exact(sock, 2))[0]
                data = receive_exact(sock, length)
            else:
                sock.send(query)
                data = sock.recv(4096)
        qid, flags, _, answers, _, _ = struct.unpack("!6H", data[:12])
        if (qid != 0x5053 or flags & 15 or not answers
                or not data.endswith(socket.inet_aton(os.environ["HOST_IP"]))):
            raise RuntimeError("DNS non restituisce HOST_IP per la guida")
    for secure in (False, True):
        conn = (http.client.HTTPSConnection("127.0.0.1", 443, timeout=2,
                                          context=ssl._create_unverified_context()) if secure
                else http.client.HTTPConnection("127.0.0.1", 80, timeout=2))
        try:
            conn.request("GET", "/document/it/ps5/index.html",
                         headers={"Host": "manuals.playstation.net"})
            response = conn.getresponse()
            if response.status != 200 or not response.read(128):
                raise RuntimeError("Pagina guida non disponibile")
        finally:
            conn.close()


if __name__ == "__main__":
    try:
        check()
    except Exception as exc:
        print(f"Healthcheck: {exc}")
        raise SystemExit(1)
