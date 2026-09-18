import os
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(b'{"status":"ok"}'); return
        return super().do_GET()

port=int(os.environ.get('PORT','8080'))
ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()
