"""Optional display adapter. No QMT, task engine or runtime lifecycle imports."""
import mimetypes


def serve_static(handler, path, read_asset, markdown_paths=(), enabled=True):
    if not enabled:
        handler._write_json({'ok': False, 'error': 'Web display is disabled; core services remain available'}, 404)
        return
    try:
        relative, raw = read_asset(path)
    except PermissionError:
        handler._write_json({'ok': False, 'error': 'forbidden'}, 403)
        return
    if raw is None:
        handler._write_json({'ok': False, 'error': 'not found'}, 404)
        return
    content_type = mimetypes.guess_type(relative)[0] or 'application/octet-stream'
    if relative in markdown_paths:
        content_type = 'text/markdown; charset=utf-8'
    try:
        handler.send_response(200)
        handler.send_header('Content-Type', content_type)
        handler.send_header('Content-Length', str(len(raw)))
        handler.send_header('Cache-Control', 'no-store')
        handler.end_headers()
        handler.wfile.write(raw)
    except OSError:
        pass
