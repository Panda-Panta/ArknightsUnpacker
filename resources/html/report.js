(() => {
  'use strict';
  const input = document.getElementById('report-search');
  const status = document.getElementById('search-status');
  if (!input || !status) return;
  const sections = [...document.querySelectorAll('[data-report-section]')];
  const blocks = [...document.querySelectorAll('[data-report-block]')];
  const skills = [...document.querySelectorAll('[data-skill]')];
  const modules = [...document.querySelectorAll('[data-module]')];
  const details = [...document.querySelectorAll('details.block')];
  const bars = [...document.querySelectorAll('.controls[data-group]')];
  const empty = document.getElementById('search-empty');
  const state = { query: '', selection: {}, stages: new Map() };
  let searchOpen = null;
  let printing = null;
  const normalize = value => value.toLocaleLowerCase().trim();
  const visible = element => !element.closest('[hidden]');
  const hasVisibleBlock = element => [...element.querySelectorAll('[data-report-block]')].some(visible);
  const searchText = new Map(blocks.map(block => {
    const entry = block.closest('[data-entry-title]');
    const group = block.closest('[data-report-section]');
    return [block, normalize((entry ? entry.dataset.entryTitle : '') + ' ' +
      (group ? group.dataset.reportGroup : '') + ' ' + block.textContent)];
  }));

  bars.forEach(bar => {
    const buttons = [...bar.querySelectorAll('button[data-tab]')];
    state.selection[bar.dataset.group] = buttons.some(button => button.dataset.tab === 'all')
      ? 'all' : (buttons[0] ? buttons[0].dataset.tab : 'all');
  });
  modules.forEach(module => {
    const levels = [...module.querySelectorAll('[data-module-stage]')].map(panel => Number(panel.dataset.moduleStage));
    state.stages.set(module.dataset.module, levels.length ? String(Math.max(...levels)) : 'all');
  });
  document.querySelectorAll('.auxiliary details.block, [data-module-intro] details.block').forEach(detail => { detail.open = false; });

  function clearHighlights() {
    const parents = new Set();
    document.querySelectorAll('mark[data-search-hit]').forEach(mark => {
      parents.add(mark.parentNode);
      mark.replaceWith(document.createTextNode(mark.textContent));
    });
    parents.forEach(parent => parent.normalize());
  }

  function highlight(query) {
    if (!query) return;
    blocks.filter(visible).forEach(block => {
      const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT);
      const texts = [];
      while (walker.nextNode()) {
        if (normalize(walker.currentNode.nodeValue).includes(query)) texts.push(walker.currentNode);
      }
      texts.forEach(node => {
        const text = node.nodeValue;
        const lower = text.toLocaleLowerCase();
        const fragment = document.createDocumentFragment();
        let start = 0;
        let found = lower.indexOf(query);
        while (found !== -1) {
          fragment.append(document.createTextNode(text.slice(start, found)));
          const mark = document.createElement('mark');
          mark.dataset.searchHit = '';
          mark.textContent = text.slice(found, found + query.length);
          fragment.append(mark);
          start = found + query.length;
          found = lower.indexOf(query, start);
        }
        fragment.append(document.createTextNode(text.slice(start)));
        node.replaceWith(fragment);
      });
    });
  }

  function syncControls() {
    bars.forEach(bar => bar.querySelectorAll('button[data-tab]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.tab === state.selection[bar.dataset.group]));
    }));
    modules.forEach(module => module.querySelectorAll('[data-stage-controls] button').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.stage === state.stages.get(module.dataset.module)));
    }));
  }

  function apply() {
    clearHighlights();
    const query = state.query;
    // Recompute from the whole document so prior tabs/levels cannot hide a hit.
    [...sections, ...skills, ...modules, ...document.querySelectorAll('[data-module-stage]')]
      .forEach(panel => { panel.hidden = false; });
    blocks.forEach(block => { block.hidden = Boolean(query && !searchText.get(block).includes(query)); });
    skills.forEach(panel => {
      panel.hidden = query ? !hasVisibleBlock(panel)
        : state.selection['技能'] !== 'all' && panel.dataset.skill !== state.selection['技能'];
    });
    modules.forEach(module => {
      module.querySelectorAll('[data-module-stage]').forEach(panel => {
        panel.hidden = query ? !hasVisibleBlock(panel)
          : state.stages.get(module.dataset.module) !== 'all' && panel.dataset.moduleStage !== state.stages.get(module.dataset.module);
      });
      module.hidden = query ? !hasVisibleBlock(module)
        : state.selection['模组'] !== 'all' && module.dataset.module !== state.selection['模组'];
    });
    sections.forEach(section => {
      section.hidden = section.dataset.reportGroup === '草稿警告' ? false : !hasVisibleBlock(section);
    });
    if (query) {
      blocks.filter(visible).forEach(block => block.querySelectorAll('details.block').forEach(detail => { detail.open = true; }));
      const matches = blocks.filter(block => visible(block) && searchText.get(block).includes(query)).length;
      empty.hidden = matches !== 0;
      status.textContent = matches ? '找到 ' + matches + ' 处资料，已高亮“' + input.value.trim() + '”。'
        : '未找到“' + input.value.trim() + '”，可修改关键词或清除搜索。';
      highlight(query);
    } else {
      empty.hidden = true;
    }
    syncControls();
  }

  function leaveSearch() {
    state.query = '';
    input.value = '';
    clearHighlights();
    if (searchOpen) {
      searchOpen.forEach((open, detail) => { detail.open = open; });
      searchOpen = null;
    }
  }

  function openPanel(panel) {
    if (!panel) return;
    panel.querySelectorAll('details.block').forEach(detail => {
      if (!detail.closest('[data-module-intro]') || panel.matches('[data-module-intro]')) detail.open = true;
    });
  }

  function locate(element) {
    if (!element) return;
    element.scrollIntoView({ behavior: 'auto', block: 'start' });
    const section = element.closest('[data-report-section]') || element;
    document.querySelectorAll('aside a').forEach(link => {
      if (link.hash.slice(1) === section.id) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    });
  }

  input.addEventListener('input', () => {
    const next = normalize(input.value);
    if (next && !state.query) searchOpen = new Map(details.map(detail => [detail, detail.open]));
    if (!next) {
      leaveSearch();
      apply();
      status.textContent = '已清除搜索，恢复原来的技能和模组选择。';
      return;
    }
    state.query = next;
    apply();
  });
  document.getElementById('clear-search').addEventListener('click', () => {
    leaveSearch();
    apply();
    status.textContent = '已清除搜索，恢复原来的技能和模组选择。';
    input.focus();
  });

  bars.forEach(bar => bar.addEventListener('click', event => {
    const button = event.target.closest('button[data-tab]');
    if (!button || !bar.contains(button)) return;
    leaveSearch();
    const group = bar.dataset.group;
    state.selection[group] = button.dataset.tab;
    apply();
    const panels = group === '技能' ? skills : modules;
    const chosen = button.dataset.tab === 'all' ? null : panels.find(panel =>
      (group === '技能' ? panel.dataset.skill : panel.dataset.module) === button.dataset.tab);
    if (chosen) openPanel(chosen);
    else panels.forEach(openPanel);
    status.textContent = '已显示：' + button.textContent.trim() + '。';
    locate(chosen || bar.closest('[data-report-section]'));
  }));

  modules.forEach(module => module.querySelectorAll('[data-stage-controls]').forEach(bar => {
    bar.addEventListener('click', event => {
      const button = event.target.closest('button[data-stage]');
      if (!button || !bar.contains(button)) return;
      leaveSearch();
      state.stages.set(module.dataset.module, button.dataset.stage);
      apply();
      const chosen = [...module.querySelectorAll('[data-module-stage]')].find(panel =>
        panel.dataset.moduleStage === button.dataset.stage);
      if (chosen) openPanel(chosen);
      else module.querySelectorAll('[data-module-stage]').forEach(openPanel);
      status.textContent = '已显示：' + module.dataset.entryTitle + ' · ' + button.textContent.trim() + '。';
      locate(chosen || module);
    });
  }));

  [['expand-all', true], ['collapse-all', false]].forEach(([id, open]) => {
    document.getElementById(id).addEventListener('click', () => {
      details.forEach(detail => { detail.open = open; });
      if (searchOpen) searchOpen = new Map(details.map(detail => [detail, open]));
      status.textContent = open ? '已展开全部资料，技能和模组仍按当前选择显示。'
        : '已收起全部资料，点击各条标题可再次展开。';
    });
  });

  function beforePrint() {
    if (printing) return;
    const panels = [...document.querySelectorAll('[data-report-section], [data-report-block], [data-skill], [data-module], [data-module-stage]')];
    printing = { panels: panels.map(panel => [panel, panel.hidden]), details: details.map(detail => [detail, detail.open]) };
    panels.forEach(panel => { panel.hidden = false; });
    details.forEach(detail => { detail.open = true; });
  }

  function afterPrint() {
    if (!printing) return;
    printing.panels.forEach(([panel, hidden]) => { panel.hidden = hidden; });
    printing.details.forEach(([detail, open]) => { detail.open = open; });
    printing = null;
  }

  document.getElementById('print-report').addEventListener('click', () => {
    beforePrint();
    try { window.print(); } finally { afterPrint(); }
  });
  window.addEventListener('beforeprint', beforePrint);
  window.addEventListener('afterprint', afterPrint);

  function followAnchor(target) {
    if (!target) return;
    leaveSearch();
    const skill = target.closest('[data-skill]');
    const module = target.closest('[data-module]');
    const stage = target.closest('[data-module-stage]');
    if (skill) state.selection['技能'] = skill.dataset.skill;
    if (module) state.selection['模组'] = module.dataset.module;
    if (module && stage) state.stages.set(module.dataset.module, stage.dataset.moduleStage);
    apply();
    openPanel(target.closest('[data-report-block]') || target);
    locate(target);
  }
  document.querySelectorAll('a[href^="#"]').forEach(link => link.addEventListener('click', event => {
    const target = document.getElementById(link.hash.slice(1));
    if (!target) return;
    event.preventDefault();
    followAnchor(target);
    history.replaceState(null, '', link.hash);
    status.textContent = '已定位：' + link.textContent.trim() + '。';
  }));

  apply();
  document.documentElement.classList.add('js');
  const tools = document.querySelector('.report-tools');
  const measure = () => document.documentElement.style.setProperty('--toolbar-height', tools.getBoundingClientRect().height + 'px');
  if (window.ResizeObserver) new ResizeObserver(measure).observe(tools);
  measure();
  if (location.hash) {
    try { followAnchor(document.getElementById(decodeURIComponent(location.hash.slice(1)))); } catch (_) {}
  }
})();
