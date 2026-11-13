"""本地预览看板：python scripts/serve.py  → http://127.0.0.1:8000/"""
import http.server
import os
import socketserver

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
PORT = int(os.getenv("PORT", "8000"))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


if __name__ == "__main__":
    os.chdir(ROOT)
    with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
        print(f"看板预览：http://127.0.0.1:{PORT}/")
        httpd.serve_forever()
