"""Local UNIX socket -> Bridge loopback. No listening TCP ports or credentials."""
import os
import selectors
import socket
import socketserver

PATH = '/mail/imap.sock'

class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        with socket.create_connection(('127.0.0.1', 1143), timeout=30) as upstream:
            upstream.settimeout(None)
            with selectors.DefaultSelector() as sel:
                sel.register(self.request, selectors.EVENT_READ, upstream)
                sel.register(upstream, selectors.EVENT_READ, self.request)
                while True:
                    events = sel.select(timeout=300)
                    if not events:
                        return
                    for key, _ in events:
                        data = key.fileobj.recv(65536)
                        if not data:
                            return
                        key.data.sendall(data)

class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    def handle_error(self, request, client_address):
        print('IMAP socket connection closed unexpectedly', flush=True)

os.umask(0o077)
if os.path.exists(PATH):
    os.unlink(PATH)
with Server(PATH, Handler) as server:
    print('Private IMAP socket ready', flush=True)
    server.serve_forever()
