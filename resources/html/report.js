
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
