#!/usr/bin/env node
'use strict';

// Usage: NODE_PATH=<bundled node_modules> node scripts/verify-html.cjs
//   --html <exported report.html> [--html <another.html>] --output <evidence directory>
// Requires Playwright and a locally installed Edge; this never downloads a browser.
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const reportStyles = JSON.parse(fs.readFileSync(path.join(__dirname, '../resources/report_styles.json'), 'utf8'));

function argumentsOf(argv) {
  const result = {html: [], output: '', channel: 'msedge'};
  for (let index = 0; index < argv.length; index++) {
    const key = argv[index];
    if (!['--html', '--output', '--channel'].includes(key) || !argv[index + 1]) {
      throw new Error('Usage: verify-html.cjs --html <report.html> [--html <report.html>] --output <directory> [--channel msedge]');
    }
    const value = argv[++index];
    if (key === '--html') result.html.push(path.resolve(value));
    else result[key.slice(2)] = value;
  }
  if (!result.html.length || !result.output) throw new Error('Both --html and --output are required.');
  result.output = path.resolve(result.output);
  return result;
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function slug(value) {
  return value.replace(/[^a-z0-9_-]/gi, '-').slice(0, 70);
}

async function stateOf(page) {
  return page.evaluate(() => ({
    query: document.querySelector('#report-search')?.value ?? '',
    entries: [...document.querySelectorAll('[data-skill],[data-module],[data-report-block]')].map(node => ({id: node.id, hidden: node.hidden})),
    details: [...document.querySelectorAll('details.block')].map((details, index) => ({id: details.id || index, open: details.open}))
  }));
}

async function offlineContext(browser, options, evidence) {
  const context = await browser.newContext({...options, serviceWorkers: 'block'});
  await context.setOffline(true);
  await context.route('**/*', async route => {
    if (/^(?:https?|wss?):/i.test(route.request().url())) {
      evidence.remoteAttempts.push(route.request().url());
      await route.abort('blockedbyclient');
    } else await route.continue();
  });
  if (typeof context.routeWebSocket === 'function') {
    await context.routeWebSocket('**/*', socket => {
      evidence.remoteAttempts.push(socket.url());
      socket.close();
    });
  }
  return context;
}

async function verifyReport(browser, filename, directory) {
  fs.mkdirSync(directory, {recursive: true});
  const result = {html: filename, fileUrl: pathToFileURL(filename).href, checks: [], pageErrors: [], remoteAttempts: [],
    screenshots: [], printBoundary: 'Stubbed window.print dispatches beforeprint/afterprint; no physical print or print-dialog claim.'};
  const context = await offlineContext(browser, {viewport: {width: 1450, height: 1050}}, result);
  const page = await context.newPage();
  page.setDefaultTimeout(2500);
  page.on('pageerror', error => result.pageErrors.push(error.message));
  async function capture(name, fullPage = false) {
    const target = path.join(directory, name + '.png');
    try {
      await page.screenshot({path: target, fullPage, animations: 'disabled', timeout: 10000});
      result.screenshots.push(target);
    } catch (error) { result.screenshotError = error.message; }
  }
  async function check(name, run) {
    try { result.checks.push({name, passed: true, evidence: await run()}); }
    catch (error) {
      result.checks.push({name, passed: false, error: error.message});
      await capture('failure-' + slug(name));
    }
    fs.writeFileSync(path.join(directory, 'result.json'), JSON.stringify(result, null, 2));
  }
  const panels = group => page.locator(group === '技能' ? '[data-skill]' : '[data-module]');
  try {
    await page.goto(result.fileUrl, {waitUntil: 'load', timeout: 20000});
    await capture('desktop-1450');
    await check('selected-theme-shared-palette-and-fonts', async () => {
      const actual = await page.evaluate(() => {
        const color = (selector, property) => {
          const element = document.querySelector(selector);
          return element ? getComputedStyle(element)[property] : null;
        };
        return {theme: document.documentElement.dataset.reportTheme,
          colorScheme: getComputedStyle(document.documentElement).colorScheme,
          canvas: color('body', 'backgroundColor'), paper: color('main', 'backgroundColor'),
          ink: color('body', 'color'), header: color('details.block > summary', 'backgroundColor'),
          bar: color('.page-bar', 'backgroundColor'), font: color('body', 'fontFamily'),
          selected: color('.controls button[aria-pressed="true"], [data-stage-controls] button[aria-pressed="true"]', 'backgroundColor')};
      });
      assert(['light', 'dark'].includes(actual.theme), 'Report must identify the selected light/dark export theme');
      const colors = reportStyles.themes[actual.theme];
      const rgb = hex => 'rgb(' + [1, 3, 5].map(offset => parseInt(hex.slice(offset, offset + 2), 16)).join(', ') + ')';
      for (const role of ['canvas', 'paper', 'ink', 'header', 'bar']) {
        if (actual[role] !== null) assert(actual[role] === rgb(colors[role]), `${role} must use shared ${actual.theme} palette: ${actual[role]}`);
      }
      if (actual.selected !== null) assert(actual.selected === rgb(colors.selected_bg), 'Selected control has the wrong theme');
      assert(actual.colorScheme === actual.theme, 'Native form-control color scheme does not match export theme');
      assert(actual.font.includes('Microsoft YaHei'), 'Report body does not use the shared CJK font stack');
      return actual;
    });
    await check('semantic-parent-markup-and-no-selection-controls', async () => {
      const structure = await page.evaluate(() => ({
        sections: document.querySelectorAll('[data-report-section]').length,
        skills: [...document.querySelectorAll('[data-skill]')].map(element => ({id: element.id, entry: element.getAttribute('data-skill')})),
        modules: [...document.querySelectorAll('[data-module]')].map(element => ({id: element.id, entry: element.getAttribute('data-module')})),
        selectionControls: document.querySelectorAll('[data-tab],[data-stage],[data-stage-controls],[data-module-stage]').length,
        duplicateIds: [...document.querySelectorAll('[id]')].map(element => element.id).filter((id, index, all) => all.indexOf(id) !== index),
        noneText: /\bNone\b|\[object Object\]/.test(document.querySelector('main')?.innerText || '')
      }));
      assert(structure.sections > 0, 'Missing report sections');
      assert(structure.skills.length > 0 || structure.modules.length > 0, 'No skill or actual module entry to verify');
      assert(!structure.duplicateIds.length, 'Duplicate HTML IDs: ' + structure.duplicateIds.join(', '));
      assert(!structure.noneText, 'Visible None/[object Object] placeholder');
      assert(structure.selectionControls === 0, 'Skills/modules/levels must be shown directly, with no selection controls');
      return structure;
    });
    await check('collapse-expand-report-only', async () => {
      assert(await page.locator('#collapse-all').count(), 'Missing #collapse-all');
      const total = await page.locator('details.block').count();
      assert(total > 0, 'No report details.block elements');
      const before = await stateOf(page);
      const directoryBefore = await page.locator('details:not(.block)').evaluateAll(nodes => nodes.map(node => node.open));
      await page.locator('#collapse-all').click();
      assert(await page.locator('details.block[open]').count() === 0, 'Collapse must close every report block');
      assert((await page.locator('#search-status').innerText()).trim(), 'Collapse feedback must be visible');
      const directoryAfter = await page.locator('details:not(.block)').evaluateAll(nodes => nodes.map(node => node.open));
      assert(JSON.stringify(directoryBefore) === JSON.stringify(directoryAfter), 'Report collapse must preserve directory details state');
      await page.locator('#expand-all').click();
      assert(await page.locator('details.block[open]').count() === total, 'Expand must open every report block');
      const after = await stateOf(page);
      assert(JSON.stringify(before.entries) === JSON.stringify(after.entries), 'Expand/collapse changed which entries are present');
      return {reportDetails: total, directoryBefore, directoryAfter};
    });
    await check('all-skills-visible-and-keyboard-anchor-navigation', async () => {
      const count = await panels('技能').count();
      if (!count) return {notApplicable: 'Module-only report'};
      assert(await panels('技能').locator('visible=true').count() === count, 'Every skill must be visible without selecting a tab');
      const links = page.locator('.skill-directory a');
      if (count > 1) {
        assert(await links.count() === count, 'Skill anchor directory must represent every skill');
        const targetId = (await links.last().getAttribute('href')).slice(1);
        await links.last().focus();
        await page.keyboard.press('Enter');
        const geometry = await page.evaluate(id => { const node = document.getElementById(id); return {text: node?.innerText, y: node?.getBoundingClientRect().y}; }, targetId);
        assert(geometry.text && geometry.text.trim().length > 20, 'Skill anchor points to incomplete content');
        assert(geometry.y >= 0 && geometry.y < 1050, 'Skill anchor did not scroll into view');
        assert(await panels('技能').locator('visible=true').count() === count, 'Navigating to a skill hid another skill');
      }
      await capture('skills-all-visible');
      return {skillPanels: count, anchorLinks: await links.count()};
    });
    await check('all-modules-visible-with-four-state-category-matrices', async () => {
      const count = await panels('模组').count();
      if (!count) return {notApplicable: 'Operator has no upgradable module'};
      assert(await panels('模组').locator('visible=true').count() === count, 'All modules must be visible together');
      const matrices = await page.locator('[data-module-matrix]').evaluateAll(nodes => nodes.map(table => ({
        title: table.getAttribute('aria-label'),
        columns: [...table.querySelectorAll('thead th')].map(cell => cell.textContent.trim()),
        rows: [...table.querySelectorAll('tbody tr')].map(row => [...row.children].map(cell => cell.textContent.trim()))
      })));
      assert(matrices.length >= count, 'Actual module comparison matrices are missing');
      for (const table of matrices) {
        assert(JSON.stringify(table.columns.slice(0, 5)) === JSON.stringify(['项目','未装备','1级','2级','3级']), 'Module matrix must compare baseline and all levels side by side');
        assert(table.rows.length > 0 && table.rows.every(row => row.length === table.columns.length && row.every(value => value.length > 0)), 'Matrix contains missing cells or dropped levels');
      }
      const links = page.locator('.module-directory a');
      if (count > 1) {
        assert(await links.count() === count, 'Module anchor directory must represent every module');
        await links.last().click();
        assert(await panels('模组').locator('visible=true').count() === count, 'Module navigation hid another module');
      }
      await capture('modules-all-levels-together');
      return {actualModules: count, matrices};
    });
    let searchQuery = '';
    await check('search-all-entries-and-matrix-cells-clear-restores', async () => {
      assert(await page.locator('#clear-search').count(), 'Missing #clear-search');
      const available = await panels('技能').count() ? panels('技能') : panels('模组');
      assert(await available.count() > 0, 'No searchable business entries');
      const heading = available.last().locator('h2,h3,h4').first();
      searchQuery = (await heading.textContent()).trim();
      assert(searchQuery.length > 1, 'No usable data-derived search term');
      const before = await stateOf(page);
      const input = page.locator('#report-search');
      assert(await page.getByRole('searchbox', {name: /页面搜索/}).count() === 1, 'Search requires an accessible 页面搜索 label');
      await input.fill(searchQuery);
      assert(await page.locator('[data-report-section] mark:visible').count() > 0, 'Search must highlight visible matches');
      assert((await page.locator('#search-status').innerText()).trim(), 'Search feedback missing');
      assert(!await page.locator('#search-empty').isVisible(), 'Successful search must not show no-match feedback');
      let matrixQuery = '';
      const cells = page.locator('[data-module-matrix] tbody td');
      if (await cells.count()) {
        matrixQuery = (await cells.last().textContent()).trim();
        await input.fill(matrixQuery);
        assert(await page.locator('[data-module-matrix] mark:visible').count() > 0, 'Matrix values must be searchable');
      }
      await input.fill('__AK_REPORT_NO_MATCH_20261020__');
      assert(await page.locator('#search-empty').isVisible(), 'Unmatched search must show #search-empty');
      await page.locator('#clear-search').click();
      const after = await stateOf(page);
      assert(after.query === '', 'Clear button did not clear the search input');
      assert(JSON.stringify(before) === JSON.stringify(after), 'Clearing search did not restore all entries and fold states');
      assert(!await page.locator('#search-empty').isVisible(), 'Cleared search still displays no-match feedback');
      assert(await page.locator('mark').count() === 0, 'Cleared search left stale match highlights');
      return {query: searchQuery, matrixQuery, before, after};
    });
    await check('print-events-expose-all-and-restore-state', async () => {
      assert(await page.locator('#print-report').count(), 'Missing #print-report');
      await page.locator('#collapse-all').click();
      if (searchQuery) await page.locator('#report-search').fill(searchQuery);
      const before = await stateOf(page);
      await page.evaluate(() => {
        window.print = () => {
          window.dispatchEvent(new Event('beforeprint'));
          window.__verifyPrint = {
            open: document.querySelectorAll('details.block[open]').length,
            total: document.querySelectorAll('details.block').length,
            query: document.querySelector('#report-search').value,
            hidden: [...document.querySelectorAll('[data-report-section],[data-report-block],[data-skill],[data-module]')].filter(node =>
              node.hidden || getComputedStyle(node).display === 'none').map(node => node.id || node.outerHTML.slice(0, 80))
          };
          window.dispatchEvent(new Event('afterprint'));
        };
      });
      await page.locator('#print-report').click();
      const during = await page.evaluate(() => window.__verifyPrint);
      const after = await stateOf(page);
      assert(during, 'Print button did not call window.print');
      assert(during.open === during.total && during.total > 0, 'Print must expand every report block');
      assert(during.hidden.length === 0, 'Print must remove search/tab/stage filtering from report content');
      assert(JSON.stringify(before) === JSON.stringify(after), 'afterprint did not restore exact search/tab/stage/fold state');
      const colors = () => page.evaluate(() => ({theme: document.documentElement.dataset.reportTheme,
        scheme: getComputedStyle(document.documentElement).colorScheme,
        paper: getComputedStyle(document.querySelector('main')).backgroundColor,
        ink: getComputedStyle(document.body).color}));
      const screenColors = await colors();
      await page.emulateMedia({media: 'print'});
      const printColors = await colors();
      const rgb = hex => 'rgb(' + [1, 3, 5].map(offset => parseInt(hex.slice(offset, offset + 2), 16)).join(', ') + ')';
      assert(printColors.paper === rgb(reportStyles.themes.light.paper) && printColors.ink === rgb(reportStyles.themes.light.ink), 'Print must use the shared light paper palette');
      assert(printColors.scheme === 'light', 'Print form controls must use light color scheme');
      await capture('print-css-1450');
      await page.emulateMedia({media: 'screen'});
      assert(JSON.stringify(screenColors) === JSON.stringify(await colors()), 'Leaving print changed the chosen screen theme');
      await page.locator('#clear-search').click();
      await page.locator('#expand-all').click();
      return {before, during, after, screenColors, printColors, actualPaperPrint: false};
    });
    await check('mobile-390-local-table-scroll', async () => {
      await page.setViewportSize({width: 390, height: 844});
      await page.evaluate(() => window.scrollTo(0, 0));
      const geometry = await page.evaluate(() => ({
        viewport: innerWidth, document: document.documentElement.scrollWidth,
        localScrollers: [...document.querySelectorAll('.table-wrap,[data-table-scroll]')].map(element => ({
          width: element.clientWidth, content: element.scrollWidth, overflow: getComputedStyle(element).overflowX
        }))
      }));
      await capture('mobile-390');
      assert(geometry.document <= geometry.viewport + 1, '390px layout overflows the document horizontally');
      assert(geometry.localScrollers.some(item => item.content > item.width && ['auto', 'scroll'].includes(item.overflow)), 'Wide report tables need local horizontal scrolling');
      return geometry;
    });
    await check('no-javascript-full-content-readable', async () => {
      const nojs = await offlineContext(browser, {javaScriptEnabled: false, viewport: {width: 1450, height: 1050}}, result);
      try {
        const fallback = await nojs.newPage();
        await fallback.goto(result.fileUrl, {waitUntil: 'load', timeout: 20000});
        const details = await fallback.locator('details.block').count();
        const open = await fallback.locator('details.block[open]').count();
        const selectors = ['[data-report-section]', '[data-report-block]', '[data-skill]', '[data-module]'];
        const counts = {};
        for (const selector of selectors) {
          counts[selector] = {total: await fallback.locator(selector).count(), visible: await fallback.locator(selector).locator('visible=true').count()};
          assert(counts[selector].total === counts[selector].visible, `No-JS fallback hides ${selector}`);
        }
        assert(details > 0 && details === open, 'No-JS fallback must start with all report details open');
        assert(await fallback.locator('.controls:visible,[data-stage-controls]:visible,#report-search:visible,#print-report:visible').count() === 0, 'No-JS fallback exposes controls with no behavior');
        const target = path.join(directory, 'no-javascript-desktop.png');
        await fallback.screenshot({path: target, fullPage: false, animations: 'disabled'});
        result.screenshots.push(target);
        return {details, open, counts};
      } finally { await nojs.close(); }
    });
    await check('offline-and-no-runtime-errors', async () => {
      assert(result.pageErrors.length === 0, 'Browser runtime errors: ' + result.pageErrors.join('; '));
      assert(result.remoteAttempts.length === 0, 'Report attempted remote access: ' + result.remoteAttempts.join('; '));
      return {pageErrors: result.pageErrors, remoteAttempts: result.remoteAttempts, offline: true};
    });
  } catch (error) {
    result.checks.push({name: 'load-report', passed: false, error: error.stack});
    await capture('load-failure');
  } finally {
    result.passed = result.checks.length > 0 && result.checks.every(check => check.passed);
    fs.writeFileSync(path.join(directory, 'result.json'), JSON.stringify(result, null, 2));
    await context.close();
  }
  return result;
}

(async () => {
  let options;
  try { options = argumentsOf(process.argv.slice(2)); }
  catch (error) { console.error(error.message); process.exitCode = 1; return; }
  fs.mkdirSync(options.output, {recursive: true});
  const summary = {startedAt: new Date().toISOString(), reports: [], passed: false};
  let browser;
  try {
    const {chromium} = require('playwright');
    browser = await chromium.launch({headless: true, ...(options.channel === 'chromium' ? {} : {channel: options.channel})});
    summary.browserVersion = browser.version();
    for (let index = 0; index < options.html.length; index++) {
      const filename = options.html[index];
      const directory = path.join(options.output, `report-${String(index + 1).padStart(2, '0')}`);
      const result = await verifyReport(browser, filename, directory);
      summary.reports.push(result);
      console.log(`${result.passed ? 'PASS' : 'FAIL'} ${filename}`);
      for (const check of result.checks.filter(check => !check.passed)) console.error(`  ${check.name}: ${check.error}`);
    }
    summary.passed = summary.reports.length > 0 && summary.reports.every(report => report.passed);
  } catch (error) { summary.error = error.stack; console.error(error.stack); }
  finally {
    if (browser) await browser.close();
    summary.finishedAt = new Date().toISOString();
    fs.writeFileSync(path.join(options.output, 'summary.json'), JSON.stringify(summary, null, 2));
    process.exitCode = summary.passed ? 0 : 1;
  }
})();
