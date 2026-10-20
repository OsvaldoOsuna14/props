"""Mete data.json en la plantilla y la envuelve como página web completa.
Uso: python3 scripts/build_page.py <plantilla.html> <data.json> <salida.html> "<título>"
"""
import sys, os
tpl, data_path, out, title = sys.argv[1:5]
body = open(tpl, encoding="utf-8").read().replace("/*__DATA__*/", open(data_path, encoding="utf-8").read().replace("</", "<\\/"))
html = ('<!doctype html>\n<html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
        '<meta name="theme-color" content="#06101f"><meta name="apple-mobile-web-app-capable" content="yes">'
        f'<meta name="apple-mobile-web-app-title" content="{title}">'
        '<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}'
        'body{margin:0;font-size:14px}[hidden]{display:none!important}img{max-width:100%}</style>'
        '</head><body>\n' + body + '\n</body></html>\n')
os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
open(out, "w", encoding="utf-8").write(html)
print(out, round(len(html.encode()) / 1024), "KB")
