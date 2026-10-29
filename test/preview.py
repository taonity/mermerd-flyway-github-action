#!/usr/bin/env python3
"""Preview the generated Markdown using actual Mermaid JS. Not a custom renderer."""

import argparse
from functools import partial
from html import escape
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import sys
import webbrowser


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=root / 'test/fixtures/starter.tbls.json')
    parser.add_argument('--tables-per-row', '--tables-per-diagram', dest='tables_per_row', type=int, choices=(1, 2, 3), default=3)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--title', default='PostgreSQL database schema')
    parser.add_argument('--no-open', action='store_true')
    parser.add_argument('--mermaid-url', default='https://cdn.jsdelivr.net/npm/mermaid@11.12.2/dist/mermaid.esm.min.mjs')
    args = parser.parse_args()
    output = root / 'test/output'
    output.mkdir(parents=True, exist_ok=True)
    readme = output / 'README.md'
    readme.write_text('# Database schema\n\n<!-- mermerd-start -->\n<!-- mermerd-end -->\n', encoding='utf-8')
    spec = importlib.util.spec_from_file_location('preview_formatter', root / 'scripts/format-mermaid.py')
    formatter = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = formatter
    spec.loader.exec_module(formatter)
    source = args.source.read_text(encoding='utf-8')
    formatter.update_readme(source, readme, args.tables_per_row)
    variants = {str(n): formatter.format_markdown(source, n) for n in (1, 2, 3)}
    # This temporary viewer only invokes Mermaid. The workflow writes Markdown alone.
    html = r'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><link rel="icon" href="data:,">
<title>__TITLE__</title><style>
:root { color-scheme:light dark; --page:light-dark(#f5f8fc,#0d1117); --panel:light-dark(#ffffff,#111820); --text:light-dark(#20344d,#dce5f1); --muted:light-dark(#58708b,#a8b7cb); --border:light-dark(#d8e4f1,#354459); }
html[data-theme="light"] { color-scheme:light; } html[data-theme="dark"] { color-scheme:dark; }
body { margin:0; padding:28px; background:var(--page); color:var(--text); font:14px system-ui,sans-serif; }
main { max-width:1500px; margin:auto; } h1 { font-size:26px; margin:0 0 8px; }
p { color:var(--muted); line-height:1.6; } .mermaid { font-family:Verdana,sans-serif; margin:20px 0; padding:12px; overflow:auto; background:var(--panel); border:1px solid var(--border); border-radius:9px; }
.mermaid svg { display:block; height:auto; margin:auto; max-width:none!important; }
label { font-size:13px; font-weight:600; } select,button { padding:8px 12px; border:1px solid var(--border); border-radius:7px; color:var(--text); background:var(--panel); font:inherit; }
.toolbar { display:flex; gap:12px; align-items:center; margin-top:18px; flex-wrap:wrap; } #status { font-size:12px; color:var(--muted); }
code { font-size:12px; } details pre { white-space:pre-wrap; word-break:break-word; } summary { cursor:pointer; }
@media(max-width:600px) { body{padding:16px;} .mermaid{padding:8px;} }
</style></head><body><main><h1>__TITLE__</h1>
<p>Compact tables. Names first. Left-aligned values. Light and dark themes.</p>
<div class="toolbar"><label for="columns">Tables per row</label><select id="columns"><option>1</option><option>2</option><option selected>3</option></select><label for="theme">Theme</label><select id="theme"><option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option></select><button id="download">Download Markdown</button><span id="status" role="status">Rendering…</span></div>
<div id="diagram"></div>
<details><summary>Generated Markdown source</summary><pre><code id="source"></code></pre></details></main>
<script type="application/json" id="variants">__VARIANTS__</script><script type="module">
try {
  const theme = document.getElementById('theme');
  theme.value = new URLSearchParams(location.search).get('theme') || 'system';
  document.documentElement.dataset.theme = theme.value;
  theme.onchange = () => { document.documentElement.dataset.theme = theme.value; };
  const { default: mermaid } = await import(__MERMAID_URL__);
  mermaid.initialize({ startOnLoad:false, securityLevel:'strict' });
  const variants = JSON.parse(document.getElementById('variants').textContent);
  const select = document.getElementById('columns');
  const diagram = document.getElementById('diagram');
  select.value = String(innerWidth < 700 ? 1 : __DEFAULT_COLUMNS__);
  async function render() {
    window.previewReady = false;
    select.disabled = true;
    const markdown = variants[select.value];
    diagram.replaceChildren();
    const nodes = [...markdown.matchAll(/```mermaid\n([\s\S]*?)```/g)].map((match,index) => {
      const node = Object.assign(document.createElement('div'),{className:'mermaid',textContent:match[1]});
      diagram.append(node);
      return node;
    });
    document.getElementById('source').textContent = markdown;
    await mermaid.run({ nodes });
    nodes.forEach(node => {
      const svg = node.querySelector('svg');
      const naturalWidth = svg.viewBox.baseVal.width;
      const scale = Math.max(.85, Math.min(1, (node.clientWidth - 40) / naturalWidth));
      svg.style.width = `${naturalWidth * scale}px`;
      node.scrollTo(0,0);
    });
    window.previewColumns = Number(select.value);
    window.previewReady = true;
    select.disabled = false;
    document.getElementById('status').textContent = `${select.value} table${select.value === '1' ? '' : 's'} per row`;
  }
  select.onchange = () => render().catch(error => { window.previewError=String(error); });
  document.getElementById('download').onclick = () => {
    const url=URL.createObjectURL(new Blob([variants[select.value]],{type:'text/markdown'}));
    Object.assign(document.createElement('a'),{href:url,download:'schema.md'}).click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  await render();
} catch(error) {
  window.previewError = String(error);
  document.body.append(Object.assign(document.createElement('pre'), { textContent:String(error) }));
}
</script></body></html>'''.replace('__TITLE__', escape(args.title)).replace('__MERMAID_URL__', json.dumps(args.mermaid_url).replace('<', '\\u003c')).replace('__VARIANTS__', json.dumps(variants).replace('<', '\\u003c')).replace('__DEFAULT_COLUMNS__', str(args.tables_per_row))
    (output / 'preview.html').write_text(html, encoding='utf-8', newline='\n')
    server = ThreadingHTTPServer(('127.0.0.1', args.port), partial(SimpleHTTPRequestHandler, directory=str(output)))
    url = f'http://127.0.0.1:{args.port}/preview.html'
    print(f'Mermaid preview: {url}\nMarkdown: {readme}\nPress Ctrl+C to stop.', flush=True)
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
