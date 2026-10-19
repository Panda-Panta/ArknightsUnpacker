"""Self contained reference pages: escaped content, no network resources."""
from base64 import b64encode
from html import escape
from pathlib import Path
from urllib.parse import quote

from ..contracts import ReportDocument
from .model import semantic_blocks

CSS = r'''
:root{color-scheme:light;--paper:#fff;--canvas:#f4f5f6;--ink:#202122;--muted:#60676f;--rule:#a9b1ba;--head:#eaecf0;--link:#2864a8}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:1rem}
body{margin:0;background:var(--canvas);color:var(--ink);font:16px/1.65 "Microsoft YaHei","PingFang SC","Noto Sans CJK SC",sans-serif}
a{color:var(--link);text-decoration:none}a:hover{text-decoration:underline}button,input{font:inherit}button{cursor:pointer;background:#fff;border:1px solid var(--rule);padding:.3rem .75rem;color:var(--link)}
:focus-visible{outline:3px solid #76a5dc;outline-offset:3px}.shell{display:grid;grid-template-columns:224px minmax(0,1fr);max-width:1450px;margin:auto;gap:24px;padding:24px}
aside{position:sticky;top:16px;align-self:start;max-height:calc(100vh - 32px);overflow:auto;font-size:.875rem}aside summary{font-size:1rem;font-weight:700;padding:8px;border-bottom:1px solid var(--rule)}aside ol{padding:0 10px 0 28px}aside li{margin:8px 0;overflow-wrap:anywhere}
main{min-width:0;background:var(--paper);border:1px solid #c8cdd2;padding:28px 32px}header{border-bottom:1px solid var(--rule);padding-bottom:18px;margin-bottom:24px}h1{font-size:2rem;line-height:1.35;overflow-wrap:anywhere;margin:0 0 10px;font-weight:600}h2{font-size:1.35rem;font-weight:600;margin:0;border-bottom:1px solid var(--rule);padding:6px 0}h2 a{float:right;font-size:1rem;font-weight:400}.subline{font-size:.85rem;color:var(--muted)}
.toolbar{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px;align-items:center}.toolbar input{min-width:150px;flex:1;padding:5px 8px;border:1px solid var(--rule)}.toolbar label{font-size:.85rem}.js-only{display:none}.js .js-only{display:flex}.controls{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0}.controls button[aria-pressed=true]{background:var(--head);color:var(--ink);font-weight:bold}
section{margin:24px 0 32px;scroll-margin-top:16px}details.block{margin:8px 0}details.block>summary{font-size:.85rem;color:var(--link);cursor:pointer;padding:4px 0}table{width:100%;border-collapse:collapse;margin:8px 0;table-layout:fixed;font-size:.95rem}th,td{border:1px solid var(--rule);padding:8px 12px;vertical-align:top;text-align:left;overflow-wrap:anywhere;white-space:pre-wrap}th{background:var(--head);font-weight:600}.key{width:23%;min-width:92px}.potential{color:#895300;font-weight:600}.empty{color:var(--muted)}.table-wrap{overflow-x:auto}table.attributes{min-width:620px}table.attributes th{white-space:normal}.portrait{display:block;max-width:150px;max-height:160px;margin:12px 0}.placeholder{padding:8px 12px;border:1px dashed #c8cdd2;display:inline-block;font-size:.8rem;color:var(--muted)}footer{font-size:.8rem;color:var(--muted);margin-top:24px;border-top:1px solid var(--rule);padding-top:12px}.search-status{font-size:.8rem;color:var(--muted)}
@media(max-width:800px){.shell{display:block;padding:10px}aside{position:static;max-height:none;margin-bottom:12px}aside ol{columns:2}main{padding:18px 14px}h1{font-size:1.6rem}th,td{padding:7px 8px}.key{width:28%}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
@media print{body{background:white;font-size:10pt}.shell{display:block;padding:0}aside,.toolbar,.controls,.js-only,summary,.placeholder{display:none!important}main{border:0;padding:0}section[hidden],details[hidden],[data-tab-hidden]{display:block!important}details.block>*{display:block!important}details.block table{display:table!important}h2{break-after:avoid}tr{break-inside:avoid}section{margin:12pt 0}a{color:inherit}h2 a{display:none}header{break-after:avoid}table{font-size:9pt}}
'''
CSS += '\n@media print{details.block>summary{display:none!important}}\n'
CSS += '\n.warning{border:2px solid #a04b14;background:#fff4e8;padding:12px}.warning h2{color:#8a3500}.warning td,.warning th{background:#fff8ef}\n'

JS = r'''
(()=>{'use strict';document.documentElement.classList.add('js');
const sections=[...document.querySelectorAll('main section')];
const input=document.getElementById('report-search');
const status=document.getElementById('search-status');
function showAll(){sections.forEach(s=>{s.hidden=false;s.removeAttribute('data-tab-hidden');s.querySelectorAll('details').forEach(d=>d.open=true)});document.querySelectorAll('.controls button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.tab==='all')))}
document.getElementById('expand-all').addEventListener('click',()=>{showAll();input.value='';status.textContent='已展开全部资料'});
document.getElementById('collapse-all').addEventListener('click',()=>document.querySelectorAll('details.block').forEach(d=>d.open=false));
document.getElementById('print-report').addEventListener('click',()=>{showAll();input.value='';window.print()});
input.addEventListener('input',()=>{showAll();const q=input.value.trim().toLocaleLowerCase();let visible=0;sections.forEach(s=>{s.hidden=q&&!s.textContent.toLocaleLowerCase().includes(q);if(!s.hidden)visible++});status.textContent=q?'找到 '+visible+' 个分区':''});
document.querySelectorAll('.controls').forEach(bar=>bar.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;const group=bar.dataset.group;sections.filter(s=>s.dataset.group===group).forEach(s=>{s.hidden=b.dataset.tab!=='all'&&s.id!==b.dataset.tab;if(s.hidden)s.setAttribute('data-tab-hidden','');else s.removeAttribute('data-tab-hidden')});bar.querySelectorAll('button').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));input.value='';status.textContent=''}));
document.querySelectorAll('aside a,h2 a').forEach(a=>a.addEventListener('click',()=>{const section=document.getElementById(a.hash.slice(1));if(section){section.hidden=false;section.removeAttribute('data-tab-hidden');section.querySelectorAll('details').forEach(d=>d.open=true)}}));
window.addEventListener('beforeprint',showAll);
})();
'''


def _e(value) -> str:
    return escape(str(value), quote=True)


def _portrait(document: ReportDocument) -> str:
    if not document.operators:
        return ''
    metadata = document.operators[0].metadata
    path = metadata.get('avatar_path') or metadata.get('portrait_path')
    if path and isinstance(path, str):
        candidate = Path(path)
        if candidate.is_file() and candidate.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'} and candidate.stat().st_size <= 5 * 1024 * 1024:
            mime = {'.png':'image/png', '.jpg':'image/jpeg', '.jpeg':'image/jpeg', '.webp':'image/webp'}[candidate.suffix.lower()]
            from PIL import Image
            try:
                with Image.open(candidate) as img:
                    img.verify()
                uri = f'data:{mime};base64,' + b64encode(candidate.read_bytes()).decode('ascii')
                return f'<img class="portrait" alt="干员肖像" src="{uri}">'
            except (OSError, ValueError):
                pass
    return '<span class="placeholder">未附本地肖像 · 完整资料见下方</span>'


def render_html(document: ReportDocument) -> str:
    blocks = semantic_blocks(document)
    nav = ''.join(f'<li><a href="#section-{i}">{_e(b.title)}</a></li>' for i, b in enumerate(blocks))
    controls = ''
    for group in ('技能', '模组'):
        entries = [(i, b) for i, b in enumerate(blocks) if b.group == group]
        if len(entries) > 1:
            buttons = ''.join(f'<button type="button" data-tab="section-{i}" aria-pressed="false">{_e(b.title)}</button>' for i, b in entries)
            controls += f'<div class="controls js-only" data-group="{group}" aria-label="{group}分区"><button type="button" data-tab="all" aria-pressed="true">全部{group}</button>{buttons}</div>'
    content = []
    for i, block in enumerate(blocks):
        rows = ''.join(f'<tr><th scope="row" class="key">{_e(k)}</th><td class="{"potential" if "潜能" in k else ""}">{_e(v)}</td></tr>' for k, v in block.rows)
        table = f'<table><tbody>{rows}</tbody></table>' if rows else ''
        if block.columns:
            heads = ''.join(f'<th scope="col">{_e(c)}</th>' for c in block.columns)
            cells = ''.join('<tr>' + ''.join(f'<td class="{"potential" if block.columns[j] == "潜能" else ""}">{_e(v)}</td>' for j, v in enumerate(row)) + '</tr>' for row in block.cells)
            table += f'<div class="table-wrap"><table class="attributes"><thead><tr>{heads}</tr></thead><tbody>{cells}</tbody></table></div>'
        content.append(f'<section id="section-{i}" class="{"warning" if block.group == "草稿警告" else ""}" data-group="{_e(block.group)}"><h2>{_e(block.title)}<a href="#section-{i}" aria-label="此分区链接">#</a></h2><details class="block" open><summary>展开／收起资料</summary>{table}</details></section>')
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' + \
        '<meta name="referrer" content="no-referrer"><title>' + _e(document.title) + '</title><style>' + CSS + '</style></head><body><div class="shell">' + \
        '<aside><details open><summary>资料目录</summary><ol>' + nav + '</ol></details></aside><main><header><h1>' + _e(document.title) + '</h1>' + \
        '<div class="subline">明日方舟 · 本地资料快照</div>' + _portrait(document) + \
        '<div class="toolbar js-only"><label for="report-search">页面搜索</label><input type="search" id="report-search" placeholder="姓名、技能、模组或正文"><button id="expand-all" type="button">展开全部</button><button id="collapse-all" type="button">收起全部</button><button id="print-report" type="button">打印</button></div><div id="search-status" class="search-status" role="status" aria-live="polite"></div></header>' + \
        controls + ''.join(content) + '<footer>由本地数据生成。PRTS仅作为资料组织与表格设计参考；本页数据来源见“来源与诊断”。</footer></main></div><script>' + JS + '</script></body></html>'


def render_index(entries: list[dict[str, str]], title: str) -> str:
    rows = ''.join('<tr>' + f'<td><a href="{quote(e["path"])}">{_e(e["title"])}</a></td>' + ''.join(f'<td>{_e(e.get(key, ""))}</td>' for key in ('profession','version','status')) + '</tr>' for e in entries)
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + _e(title) + '</title><style>' + CSS + '</style></head><body><main style="max-width:1280px;margin:24px auto"><h1>' + _e(title) + '</h1><p>离线资料目录 · 移动整个任务文件夹后仍可使用</p><div class="table-wrap"><table><thead><tr><th>资料</th><th>职业</th><th>数据版本</th><th>状态</th></tr></thead><tbody>' + rows + '</tbody></table></div></main></body></html>'
