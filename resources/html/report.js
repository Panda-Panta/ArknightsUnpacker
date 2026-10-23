(() => {
  'use strict';
  const input = document.getElementById('report-search');
  const status = document.getElementById('search-status');
  if (!input || !status) return;
  const sections = [...document.querySelectorAll('[data-report-section]')];
  const blocks = [...document.querySelectorAll('[data-report-block]')];
  const entries = [...document.querySelectorAll('[data-skill], [data-module]')];
  const details = [...document.querySelectorAll('details.block')];
  const directoryLinks = [...document.querySelectorAll('.section-directory a')];
  const scrollTables = [...document.querySelectorAll('.table-area .table-wrap')];
  const tools = document.querySelector('.report-tools');
  const empty = document.getElementById('search-empty');
  const state = { query: '' };
  let searchOpen = null;
  let printing = null;
  let layoutFrame = 0;
  let anchorPosition = null;
  const normalize = value => value.toLocaleLowerCase().trim();
  const visible = element => !element.closest('[hidden]');
  const hasVisibleBlock = element => [...element.querySelectorAll('[data-report-block]')].some(visible);
  const searchText = new Map(blocks.map(block => {
    const entry = block.closest('[data-entry-title]');
    const group = block.closest('[data-report-section]');
    const content = block.cloneNode(true);
    content.querySelectorAll('[aria-hidden="true"]').forEach(element => element.remove());
    return [block, normalize((entry ? entry.dataset.entryTitle : '') + ' ' +
      (group ? group.dataset.reportGroup : '') + ' ' + content.textContent)];
  }));

  document.querySelectorAll('.auxiliary details.block').forEach(detail => { detail.open = false; });

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
    sections.filter(visible).forEach(section => {
      const walker = document.createTreeWalker(section, NodeFilter.SHOW_TEXT);
      const texts = [];
      while (walker.nextNode()) {
        if (visible(walker.currentNode.parentElement) && !walker.currentNode.parentElement.closest('[aria-hidden="true"]') &&
            normalize(walker.currentNode.nodeValue).includes(query)) {
          texts.push(walker.currentNode);
        }
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

  function apply() {
    anchorPosition = null;
    clearHighlights();
    const query = state.query;
    [...sections, ...entries]
      .forEach(panel => { panel.hidden = false; });
    blocks.forEach(block => { block.hidden = Boolean(query && !searchText.get(block).includes(query)); });
    entries.forEach(entry => {
      entry.hidden = Boolean(query && !hasVisibleBlock(entry));
    });
    sections.forEach(section => {
      section.hidden = section.dataset.reportGroup === '草稿警告' ? false : !hasVisibleBlock(section);
    });
    if (query) {
      blocks.filter(visible).forEach(openPanel);
      const matches = blocks.filter(block => visible(block) && searchText.get(block).includes(query)).length;
      empty.hidden = matches !== 0;
      status.textContent = matches ? '找到 ' + matches + ' 处资料，已高亮“' + input.value.trim() + '”。'
        : '未找到“' + input.value.trim() + '”，可修改关键词或清除搜索。';
      highlight(query);
    } else {
      empty.hidden = true;
    }
    scheduleLayout();
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
    let ancestor = panel;
    while (ancestor) {
      if (ancestor.matches('details.block')) ancestor.open = true;
      ancestor = ancestor.parentElement;
    }
    panel.querySelectorAll('details.block').forEach(detail => { detail.open = true; });
  }

  function locate(element) {
    if (!element) return;
    element.scrollIntoView({ behavior: 'auto', block: 'start' });
    if (!element.hasAttribute('tabindex')) element.setAttribute('tabindex', '-1');
    element.focus({ preventScroll: true });
    const section = element.closest('[data-report-section]') || element;
    setCurrentSection(section.id);
    anchorPosition = section.matches('[data-report-section]') ? { id: section.id, y: window.scrollY } : null;
  }

  function setCurrentSection(id) {
    directoryLinks.forEach(link => {
      if (link.hash.slice(1) === id) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    });
  }

  function updateLocation() {
    // Near the document end several anchors share the same clamped scroll
    // position. Keep the chosen destination until the reader actually scrolls.
    if (anchorPosition && Math.abs(window.scrollY - anchorPosition.y) < 1) {
      setCurrentSection(anchorPosition.id);
      return;
    }
    anchorPosition = null;
    const readingLine = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--bar-height')) +
      tools.getBoundingClientRect().height + 32;
    const shown = sections.filter(visible);
    let current = shown[0];
    for (const section of shown) {
      if (section.getBoundingClientRect().top <= readingLine) current = section;
      else break;
    }
    if (window.scrollY > 0 && window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 4) {
      current = shown[shown.length - 1];
    }
    setCurrentSection(current ? current.id : '');
  }

  function scheduleLayout() {
    if (layoutFrame) return;
    layoutFrame = requestAnimationFrame(() => {
      layoutFrame = 0;
      if (printing) return;
      document.documentElement.style.setProperty('--toolbar-height', tools.getBoundingClientRect().height + 'px');
      scrollTables.forEach(wrapper => {
        const overflow = wrapper.clientWidth > 0 && wrapper.scrollWidth > wrapper.clientWidth + 1;
        wrapper.parentElement.dataset.overflow = String(overflow);
        wrapper.tabIndex = overflow ? 0 : -1;
      });
      updateLocation();
    });
  }

  function clearSearch() {
    leaveSearch();
    apply();
    status.textContent = '已清除搜索，恢复连续展示。';
    input.focus();
  }

  input.addEventListener('input', () => {
    const next = normalize(input.value);
    if (next && !state.query) searchOpen = new Map(details.map(detail => [detail, detail.open]));
    if (!next) {
      leaveSearch();
      apply();
      status.textContent = '已清除搜索，恢复连续展示。';
      return;
    }
    state.query = next;
    apply();
  });
  document.getElementById('clear-search').addEventListener('click', clearSearch);
  input.addEventListener('keydown', event => {
    if (event.key === 'Escape' && input.value) {
      event.preventDefault();
      clearSearch();
    }
  });

  [['expand-all', true], ['collapse-all', false]].forEach(([id, open]) => {
    document.getElementById(id).addEventListener('click', () => {
      anchorPosition = null;
      details.forEach(detail => { detail.open = open; });
      if (searchOpen) searchOpen = new Map(details.map(detail => [detail, open]));
      status.textContent = open ? '已展开全部资料。'
        : '已收起全部资料，点击各条标题可再次展开。';
      scheduleLayout();
    });
  });

  function beforePrint() {
    if (printing) return;
    const panels = [...document.querySelectorAll('[data-report-section], [data-report-block], [data-skill], [data-module]')];
    printing = { panels: panels.map(panel => [panel, panel.hidden]), details: details.map(detail => [detail, detail.open]) };
    panels.forEach(panel => { panel.hidden = false; });
    details.forEach(detail => { detail.open = true; });
  }

  function afterPrint() {
    if (!printing) return;
    printing.panels.forEach(([panel, hidden]) => { panel.hidden = hidden; });
    printing.details.forEach(([detail, open]) => { detail.open = open; });
    printing = null;
    scheduleLayout();
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
    apply();
    if (target.matches('[data-report-section], [data-report-block], [data-skill], [data-module]')) {
      openPanel(target.closest('[data-report-block]') || target);
    }
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
  if (window.ResizeObserver) {
    const observer = new ResizeObserver(scheduleLayout);
    [tools, ...scrollTables].forEach(element => observer.observe(element));
  }
  window.addEventListener('scroll', scheduleLayout, { passive: true });
  window.addEventListener('resize', () => { anchorPosition = null; scheduleLayout(); });
  details.forEach(detail => detail.addEventListener('toggle', scheduleLayout));
  const followHash = () => {
    try { followAnchor(document.getElementById(decodeURIComponent(location.hash.slice(1)))); } catch (_) {}
  };
  window.addEventListener('hashchange', followHash);
  document.documentElement.style.setProperty('--toolbar-height', tools.getBoundingClientRect().height + 'px');
  scheduleLayout();
  if (location.hash) {
    followHash();
  }
})();
